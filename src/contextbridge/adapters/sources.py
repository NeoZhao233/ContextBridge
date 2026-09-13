from __future__ import annotations

import hashlib
import io
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
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


def read_session_text(path: Path, max_chars: int | None = None) -> str:
    """Read plain JSONL or DSH's default concatenated-zstd JSONL."""
    if not path.name.endswith(".zstd"):
        with path.open("r", encoding="utf-8", errors="replace") as session:
            return session.read() if max_chars is None else session.read(max_chars)

    try:
        import zstandard
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Reading compressed DSH sessions requires the optional dependency: "
            "pip install 'contextbridge[dsh]'"
        ) from error

    with path.open("rb") as compressed:
        decompressor = zstandard.ZstdDecompressor()
        with (
            decompressor.stream_reader(compressed, read_across_frames=True) as reader,
            io.TextIOWrapper(reader, encoding="utf-8", errors="replace") as session,
        ):
            return session.read() if max_chars is None else session.read(max_chars)


class JsonlSource(ABC):
    name: str

    @abstractmethod
    def text_from(self, record: dict[str, Any]) -> str | None: ...

    def session_id_from(self, path: Path, lines: list[str]) -> str:
        return path.stem

    def message_id_from(self, record: dict[str, Any], line_index: int) -> str:
        return str(line_index + 1)

    def occurred_at_from(self, record: dict[str, Any]) -> datetime | None:
        timestamp = record.get("timestamp")
        return datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None

    def sync(self, path: Path, cursor: str | None = None) -> SyncResult:
        lines = [line for line in read_session_text(path).splitlines() if line]
        start = min(int(cursor or 0), len(lines))
        session_id = self.session_id_from(path, lines)
        events: list[ContextEvent] = []
        for index, line in enumerate(lines[start:], start=start):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or not (content := self.text_from(record)):
                continue
            content = content.strip()
            message_id = self.message_id_from(record, index)
            identity = f"{self.name}\0{path}\0{message_id}\0{content}"
            event_data: dict[str, Any] = {
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "source": SourceRef(
                    agent=self.name,
                    session_id=session_id,
                    message_id=message_id,
                    path=path,
                ),
                "content": content,
            }
            if occurred_at := self.occurred_at_from(record):
                event_data["occurred_at"] = occurred_at
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


class DshSource(JsonlSource):
    """Import durable user/assistant messages from a DSH Session event log."""

    name = "dsh"

    def session_id_from(self, path: Path, lines: list[str]) -> str:
        if lines:
            try:
                header = json.loads(lines[0])
            except json.JSONDecodeError:
                header = None
            if isinstance(header, dict) and header.get("type") == "session":
                if header.get("version") != 3:
                    raise ValueError(
                        f"Unsupported DSH session format v{header.get('version')}; expected v3"
                    )
                if isinstance(header.get("id"), str):
                    return header["id"]
        return path.parent.name

    def message_id_from(self, record: dict[str, Any], line_index: int) -> str:
        sequence = record.get("seq")
        return str(sequence) if isinstance(sequence, int) else super().message_id_from(record, line_index)

    def occurred_at_from(self, record: dict[str, Any]) -> datetime | None:
        timestamp = record.get("time")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            return datetime.fromtimestamp(timestamp / 1000, tz=UTC)
        return super().occurred_at_from(record)

    def text_from(self, record: dict[str, Any]) -> str | None:
        if isinstance(record.get("surfaceOp"), dict):
            return None
        data = record.get("data")
        if not isinstance(data, dict):
            return None
        if record.get("type") == "user/message":
            return collect_text(data.get("content"))
        if record.get("type") == "assistant/message":
            return collect_text(data.get("message"))
        return None
