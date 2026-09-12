from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import ContextEvent, SourceRef, SyncResult


def collect_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [part for item in value if (part := collect_text(item))]
        return "\n".join(parts) or None
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if text := collect_text(value.get(key)):
                return text
    return None


class JsonlSource(ABC):
    name: str

    @abstractmethod
    def text_from(self, record: dict[str, Any]) -> str | None: ...

    def sync(self, path: Path, cursor: str | None = None) -> SyncResult:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        start = min(int(cursor or 0), len(lines))
        events: list[ContextEvent] = []
        for index, line in enumerate(lines[start:], start=start):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or not (content := self.text_from(record)):
                continue
            content = content.strip()
            message_id = str(index + 1)
            identity = f"{self.name}\0{path}\0{message_id}\0{content}"
            timestamp = record.get("timestamp")
            event_data: dict[str, Any] = {
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "source": SourceRef(
                    agent=self.name,
                    session_id=path.stem,
                    message_id=message_id,
                    path=path,
                ),
                "content": content,
            }
            if isinstance(timestamp, str):
                event_data["occurred_at"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            events.append(ContextEvent(**event_data))
        return SyncResult(events=events, cursor=str(len(lines)))


class ClaudeCodeSource(JsonlSource):
    name = "claude-code"

    def text_from(self, record: dict[str, Any]) -> str | None:
        if record.get("type") not in (None, "user", "assistant"):
            return None
        return collect_text(record.get("message") or record.get("content"))


class CodexSource(JsonlSource):
    name = "codex"

    def text_from(self, record: dict[str, Any]) -> str | None:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") == "response_item" and payload.get("type") != "message":
            return None
        return collect_text(
            payload.get("message")
            or payload.get("content")
            or record.get("message")
            or record.get("content")
        )
