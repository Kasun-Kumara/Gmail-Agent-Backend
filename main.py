from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent_service import clear_conversation, run_chat
from .architecture import architecture_state
from .gmail_service import approve_draft, cancel_draft, list_drafts


app = FastAPI(title="Gmail AI Agent Web App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    drafts: list[dict]
    architecture: dict


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message is required.")
    try:
        reply = run_chat(payload.message.strip())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "reply": reply,
        "drafts": list_drafts(),
        "architecture": architecture_state.snapshot(),
    }


@app.post("/api/chat/reset")
def reset_chat():
    clear_conversation()
    architecture_state.reset_for_chat()
    return {"status": "reset", "architecture": architecture_state.snapshot()}


@app.get("/api/drafts")
def drafts():
    return {"drafts": list_drafts()}


@app.post("/api/drafts/{draft_id}/approve")
def approve(draft_id: str):
    try:
        result = approve_draft(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found.") from exc
    return {"result": result, "drafts": list_drafts(), "architecture": architecture_state.snapshot()}


@app.post("/api/drafts/{draft_id}/cancel")
def cancel(draft_id: str):
    try:
        result = cancel_draft(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found.") from exc
    return {"result": result, "drafts": list_drafts(), "architecture": architecture_state.snapshot()}


@app.get("/api/architecture/state")
def architecture():
    return architecture_state.snapshot()
