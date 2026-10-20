from __future__ import annotations

import os
import re
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from ddgs import DDGS
from langchain_core.tools import tool
from langchain_groq import ChatGroq

from .architecture import architecture_state
from .gmail_service import (
    create_pending_email,
    list_drafts,
    read_email,
    reply_to_email,
    search_emails,
    send_email,
)
from .prompts import SYSTEM_PROMPT


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

_agent = None
conversation_history: list[dict[str, str]] = []
MAX_HISTORY_MESSAGES = 20


def clear_dead_local_proxy() -> None:
    """Avoid inherited local proxy settings that block outbound LLM calls."""
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        value = os.environ.get(key, "")
        if value.startswith("http://127.0.0.1:9") or value.startswith("http://localhost:9"):
            os.environ.pop(key, None)


@tool
def web_search(query: str) -> str:
    """Search the web for current information and return concise result snippets with links."""
    clear_dead_local_proxy()
    architecture_state.mark(
        "web",
        f'Searched the web: "{query}"',
        ["agent", "web_search"],
        ["agent-web"],
    )
    try:
        results = list(DDGS().text(query, region="us-en", safesearch="moderate", max_results=5))
    except Exception as exc:
        return f"Web search failed: {exc}"

    if not results:
        return f'No web results found for "{query}". Try a more specific query.'

    lines = []
    for index, item in enumerate(results, start=1):
        title = item.get("title") or "Untitled"
        href = item.get("href") or item.get("url") or ""
        body = item.get("body") or ""
        lines.append(f"{index}. {title}\nURL: {href}\nSummary: {body}")
    return "\n\n".join(lines)


def get_agent():
    global _agent
    if _agent is not None:
        return _agent

    clear_dead_local_proxy()
    groq_api_key = os.getenv("GROQ_API_KEY") or os.getenv("Groq_API")
    if not groq_api_key:
        raise RuntimeError("Missing Groq_API in .env")

    os.environ["GROQ_API_KEY"] = groq_api_key
    llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)

    tools = [web_search, search_emails, read_email, send_email, reply_to_email]

    _agent = create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)
    return _agent


def is_new_email_request(message: str) -> bool:
    text = message.lower()
    compose_words = ("write", "compose", "draft", "send", "email", "mail")
    reply_words = ("reply", "respond")
    if any(word in text for word in reply_words):
        return False
    return "email" in text and any(word in text for word in compose_words)


def strip_markdown_label(line: str) -> str:
    return re.sub(r"^[\s>*#`_-]+|[\s`*_]+$", "", line).strip()


def parse_chat_email_draft(reply: str) -> dict[str, str] | None:
    fields: dict[str, str] = {}
    lines = reply.splitlines()
    body_start = None

    for index, raw_line in enumerate(lines):
        line = strip_markdown_label(raw_line)
        match = re.match(r"^(to|subject|body)\s*:\s*(.+)?$", line, flags=re.IGNORECASE)
        if not match:
            continue

        key = match.group(1).lower()
        value = (match.group(2) or "").strip()
        if key == "body":
            body_start = index + 1
            if value:
                fields["body"] = value
            break
        fields[key] = value

    if body_start is not None:
        rest = "\n".join(lines[body_start:]).strip()
        if rest:
            fields["body"] = f"{fields.get('body', '')}\n{rest}".strip()
    elif "subject" in fields:
        for index, raw_line in enumerate(lines):
            if re.match(r"^[\s>*#`_-]*subject\s*:", raw_line, flags=re.IGNORECASE):
                fields["body"] = "\n".join(lines[index + 1 :]).strip()
                break

    to = fields.get("to", "").strip()
    subject = fields.get("subject", "").strip()
    body = fields.get("body", "").strip()
    if not (to and subject and body):
        return None

    # Drop common explanatory wrappers if the model wrote the draft in prose.
    body = re.sub(r"^(body\s*:)?\s*", "", body, flags=re.IGNORECASE).strip()
    body = re.split(
        r"\n\s*(the email has not been sent|let me know|you can approve|ask the user)",
        body,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return {"to": to, "subject": subject, "body": body}


def ensure_pending_draft(message: str, reply: str, previous_draft_count: int) -> str:
    if not is_new_email_request(message):
        return reply
    if len(list_drafts()) > previous_draft_count:
        return reply

    parsed = parse_chat_email_draft(reply)
    if not parsed:
        return (
            f"{reply}\n\n"
            "I could not place this in Pending approvals because the draft was missing a clear "
            "To, Subject, or Body field. Please include those details and I will prepare it for approval."
        )

    draft = create_pending_email(parsed["to"], parsed["subject"], parsed["body"])
    architecture_state.mark(
        "gmail",
        f"Recovered chat draft {draft['id']} for approval",
        ["agent", "gmail_send"],
        ["agent-gmail-send"],
    )
    return (
        f"Draft {draft['id']} is waiting in Pending approvals.\n\n"
        f"To: {parsed['to']}\n"
        f"Subject: {parsed['subject']}\n\n"
        f"{parsed['body']}\n\n"
        "The email has NOT been sent."
    )


def remember_turn(user_message: str, assistant_reply: str) -> None:
    conversation_history.extend(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_reply},
        ]
    )
    if len(conversation_history) > MAX_HISTORY_MESSAGES:
        del conversation_history[:-MAX_HISTORY_MESSAGES]


def clear_conversation() -> None:
    conversation_history.clear()


def run_chat(message: str) -> str:
    architecture_state.reset_for_chat()
    previous_draft_count = len(list_drafts())
    messages = [*conversation_history, {"role": "user", "content": message}]
    response = get_agent().invoke({"messages": messages})
    reply = response["messages"][-1].content
    reply = ensure_pending_draft(message, reply, previous_draft_count)
    remember_turn(message, reply)
    architecture_state.mark(
        "chat",
        "Assistant response completed",
        ["browser", "fastapi", "agent", "groq"],
        ["browser-fastapi", "fastapi-agent", "agent-groq"],
    )
    return reply
