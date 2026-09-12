from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .models import ContextEvent, Memory, MemoryDraft, MemoryStatus, MemoryType, SourceRef, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    source_session TEXT NOT NULL,
    source_message TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    reason TEXT,
    related_files TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    source_session TEXT NOT NULL,
    source_message TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_commit TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_cursors (
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    cursor TEXT NOT NULL,
    PRIMARY KEY (source, path)
);
"""


class ContextDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    def append_events(self, events: list[ContextEvent]) -> int:
        before = self.connection.total_changes
        self.connection.executemany(
            """INSERT OR IGNORE INTO events
               (id, type, occurred_at, source_agent, source_session, source_message,
                source_path, content) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    event.id,
                    event.type,
                    event.occurred_at.isoformat(),
                    event.source.agent,
                    event.source.session_id,
                    event.source.message_id,
                    str(event.source.path),
                    event.content,
                )
                for event in events
            ],
        )
        self.connection.commit()
        return self.connection.total_changes - before

    def append_memories(self, drafts: list[MemoryDraft], source_commit: str | None) -> int:
        before = self.connection.total_changes
        rows = []
        for draft in drafts:
            identity = "\0".join(
                [
                    draft.source.agent,
                    draft.source.session_id,
                    draft.source.message_id,
                    draft.type.value,
                    draft.content,
                ]
            )
            memory_id = hashlib.sha256(identity.encode()).hexdigest()
            rows.append(
                (
                    memory_id,
                    draft.type.value,
                    draft.content,
                    draft.reason,
                    json.dumps(draft.related_files),
                    draft.source.agent,
                    draft.source.session_id,
                    draft.source.message_id,
                    str(draft.source.path),
                    source_commit,
                    MemoryStatus.ACTIVE.value,
                    utc_now().isoformat(),
                )
            )
        self.connection.executemany(
            """INSERT OR IGNORE INTO memories
               (id, type, content, reason, related_files, source_agent, source_session,
                source_message, source_path, source_commit, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self.connection.commit()
        return self.connection.total_changes - before

    def cursor(self, source: str, path: Path) -> str | None:
        row = self.connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source = ? AND path = ?",
            (source, str(path)),
        ).fetchone()
        return str(row["cursor"]) if row else None

    def set_cursor(self, source: str, path: Path, cursor: str) -> None:
        self.connection.execute(
            """INSERT INTO sync_cursors (source, path, cursor) VALUES (?, ?, ?)
               ON CONFLICT(source, path) DO UPDATE SET cursor = excluded.cursor""",
            (source, str(path), cursor),
        )
        self.connection.commit()

    def memories(self) -> list[Memory]:
        rows = self.connection.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
        return [
            Memory(
                id=row["id"],
                type=MemoryType(row["type"]),
                content=row["content"],
                reason=row["reason"],
                related_files=json.loads(row["related_files"]),
                source=SourceRef(
                    agent=row["source_agent"],
                    session_id=row["source_session"],
                    message_id=row["source_message"],
                    path=Path(row["source_path"]),
                ),
                source_commit=row["source_commit"],
                status=MemoryStatus(row["status"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_possibly_stale(self, memory_ids: list[str]) -> int:
        before = self.connection.total_changes
        self.connection.executemany(
            "UPDATE memories SET status = 'possibly_stale' WHERE id = ? AND status = 'active'",
            [(memory_id,) for memory_id in memory_ids],
        )
        self.connection.commit()
        return self.connection.total_changes - before

    def stats(self) -> dict[str, int]:
        def count(query: str) -> int:
            return int(self.connection.execute(query).fetchone()[0])

        return {
            "events": count("SELECT count(*) FROM events"),
            "memories": count("SELECT count(*) FROM memories"),
            "stale": count("SELECT count(*) FROM memories WHERE status = 'possibly_stale'"),
        }
