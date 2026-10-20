from __future__ import annotations

import base64
import os
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool

from .architecture import architecture_state


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"

pending_emails: dict[str, dict[str, Any]] = {}
_service = None


def get_gmail_service():
    global _service
    if _service is not None:
        return _service

    architecture_state.mark(
        "auth",
        "Loaded local Gmail auth files",
        ["fastapi", "auth_files"],
        ["gmail-auth"],
    )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    _service = build("gmail", "v1", credentials=creds)
    return _service


def get_header(headers: list[dict[str, str]], name: str) -> str:
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")


def decode_body(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8",
                errors="replace",
            )

    for part in payload.get("parts", []):
        text = decode_body(part)
        if text:
            return text

    return ""


def create_pending_email(to: str, subject: str, body: str) -> dict[str, Any]:
    draft_id = str(uuid.uuid4())[:8]
    pending_emails[draft_id] = {
        "id": draft_id,
        "type": "send",
        "to": to,
        "subject": subject,
        "body": body,
    }
    return pending_emails[draft_id]


@tool
def search_emails(query: str = "in:inbox", max_results: int = 5) -> str:
    """Search Gmail using Gmail search syntax. Return IDs, subjects, senders, dates and snippets."""
    architecture_state.mark(
        "gmail",
        f'Searched Gmail: "{query}"',
        ["agent", "gmail_search", "auth_files"],
        ["agent-gmail-search", "gmail-auth"],
    )
    service = get_gmail_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max(1, min(max_results, 20)))
        .execute()
    )

    messages = result.get("messages", [])
    output = []
    for item in messages:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        output.append(
            f"Message ID: {msg['id']}\n"
            f"Thread ID: {msg['threadId']}\n"
            f"From: {get_header(headers, 'From')}\n"
            f"Subject: {get_header(headers, 'Subject')}\n"
            f"Date: {get_header(headers, 'Date')}\n"
            f"Snippet: {msg.get('snippet', '')}"
        )

    return "\n\n---\n\n".join(output) if output else "No emails found."


@tool
def read_email(message_id: str) -> str:
    """Read the full content of an email using its Gmail message ID."""
    architecture_state.mark(
        "gmail",
        f"Read Gmail message {message_id}",
        ["agent", "gmail_read", "auth_files"],
        ["agent-gmail-read", "gmail-auth"],
    )
    service = get_gmail_service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = msg.get("payload", {}).get("headers", [])
    body = decode_body(msg.get("payload", {}))

    return (
        f"From: {get_header(headers, 'From')}\n"
        f"To: {get_header(headers, 'To')}\n"
        f"Subject: {get_header(headers, 'Subject')}\n"
        f"Message ID: {msg['id']}\n"
        f"Thread ID: {msg['threadId']}\n\n"
        f"{body or msg.get('snippet', '')}"
    )


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Prepare an email draft for user review. Never send the email directly."""
    architecture_state.mark(
        "gmail",
        "Prepared outgoing email for approval",
        ["agent", "gmail_send"],
        ["agent-gmail-send"],
    )
    draft = create_pending_email(to, subject, body)
    draft_id = draft["id"]
    return (
        f"Email prepared for approval. Draft ID: {draft_id}\n"
        f"To: {to}\nSubject: {subject}\n\n{body}\n\n"
        "The email has NOT been sent. Ask the user to review it."
    )


@tool
def reply_to_email(message_id: str, body: str) -> str:
    """Prepare a reply draft for user review. Never send the reply directly."""
    architecture_state.mark(
        "gmail",
        "Prepared Gmail reply for approval",
        ["agent", "gmail_read", "gmail_send", "auth_files"],
        ["agent-gmail-read", "agent-gmail-send", "gmail-auth"],
    )
    service = get_gmail_service()
    original = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = original.get("payload", {}).get("headers", [])

    sender = get_header(headers, "From")
    subject = get_header(headers, "Subject") or "(no subject)"
    original_message_id = get_header(headers, "Message-ID")
    references = get_header(headers, "References")

    if not sender or not original_message_id:
        return "Cannot prepare reply safely: required headers are missing."

    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    draft_id = str(uuid.uuid4())[:8]
    pending_emails[draft_id] = {
        "id": draft_id,
        "type": "reply",
        "to": sender,
        "subject": subject,
        "body": body,
        "thread_id": original["threadId"],
        "in_reply_to": original_message_id,
        "references": references,
    }

    return (
        f"Reply prepared for approval. Draft ID: {draft_id}\n"
        f"To: {sender}\nSubject: {subject}\n\n{body}\n\n"
        "The reply has NOT been sent. Ask the user to review it."
    )


def list_drafts() -> list[dict[str, Any]]:
    return list(pending_emails.values())


def cancel_draft(draft_id: str) -> dict[str, str]:
    if draft_id not in pending_emails:
        raise KeyError(draft_id)
    pending_emails.pop(draft_id)
    architecture_state.mark("gmail", f"Cancelled draft {draft_id}", ["gmail_send"], ["agent-gmail-send"])
    return {"status": "cancelled", "draft_id": draft_id}


def approve_draft(draft_id: str) -> dict[str, str]:
    draft = pending_emails.get(draft_id)
    if not draft:
        raise KeyError(draft_id)

    architecture_state.mark(
        "gmail",
        f"Approved and sent draft {draft_id}",
        ["fastapi", "gmail_send", "auth_files"],
        ["agent-gmail-send", "gmail-auth"],
    )

    message = EmailMessage()
    message["To"] = draft["to"]
    message["Subject"] = draft["subject"]
    if draft["type"] == "reply":
        message["In-Reply-To"] = draft["in_reply_to"]
        refs = f"{draft.get('references') or ''} {draft['in_reply_to']}".strip()
        if refs:
            message["References"] = refs
    message.set_content(draft["body"])

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    payload: dict[str, Any] = {"raw": raw}
    if draft["type"] == "reply":
        payload["threadId"] = draft["thread_id"]

    sent = get_gmail_service().users().messages().send(userId="me", body=payload).execute()
    pending_emails.pop(draft_id, None)
    return {"status": "sent", "draft_id": draft_id, "message_id": sent["id"]}
