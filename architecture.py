from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any


class ArchitectureState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state: dict[str, Any] = {
            "active_nodes": [],
            "active_edges": [],
            "events": [],
            "last_updated": None,
        }

    def reset_for_chat(self) -> None:
        with self._lock:
            self._state = {
                "active_nodes": ["browser", "fastapi", "agent", "groq"],
                "active_edges": ["browser-fastapi", "fastapi-agent", "agent-groq"],
                "events": [
                    {
                        "label": "Chat request received",
                        "kind": "chat",
                        "at": self._timestamp(),
                    }
                ],
                "last_updated": self._timestamp(),
            }

    def mark(self, kind: str, label: str, nodes: list[str], edges: list[str]) -> None:
        with self._lock:
            active_nodes = set(self._state["active_nodes"])
            active_edges = set(self._state["active_edges"])
            active_nodes.update(nodes)
            active_edges.update(edges)
            self._state["active_nodes"] = sorted(active_nodes)
            self._state["active_edges"] = sorted(active_edges)
            self._state["events"].insert(
                0,
                {
                    "label": label,
                    "kind": kind,
                    "at": self._timestamp(),
                },
            )
            self._state["events"] = self._state["events"][:8]
            self._state["last_updated"] = self._timestamp()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "nodes": [
                    {"id": "browser", "label": "React UI", "group": "Frontend"},
                    {"id": "fastapi", "label": "FastAPI", "group": "Backend"},
                    {"id": "agent", "label": "LangChain Agent", "group": "Reasoning"},
                    {"id": "groq", "label": "Groq LLM", "group": "Model"},
                    {"id": "web_search", "label": "Web Search", "group": "Tool"},
                    {"id": "gmail_search", "label": "Gmail Search", "group": "Tool"},
                    {"id": "gmail_read", "label": "Gmail Read", "group": "Tool"},
                    {"id": "gmail_send", "label": "Gmail Draft + Send", "group": "Tool"},
                    {"id": "auth_files", "label": "Local Auth Files", "group": "Secrets"},
                ],
                "edges": [
                    {"id": "browser-fastapi", "from": "browser", "to": "fastapi"},
                    {"id": "fastapi-agent", "from": "fastapi", "to": "agent"},
                    {"id": "agent-groq", "from": "agent", "to": "groq"},
                    {"id": "agent-web", "from": "agent", "to": "web_search"},
                    {"id": "agent-gmail-search", "from": "agent", "to": "gmail_search"},
                    {"id": "agent-gmail-read", "from": "agent", "to": "gmail_read"},
                    {"id": "agent-gmail-send", "from": "agent", "to": "gmail_send"},
                    {"id": "gmail-auth", "from": "fastapi", "to": "auth_files"},
                ],
                **self._state,
            }

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()


architecture_state = ArchitectureState()
