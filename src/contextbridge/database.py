from __future__ import annotations

import hashlib
import json
import re
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
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    content,
    reason,
    related_files
);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    event_id UNINDEXED,
    content
);
CREATE TRIGGER IF NOT EXISTS events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, event_id, content)
    VALUES (new.rowid, new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS events_fts_delete AFTER DELETE ON events BEGIN
    DELETE FROM events_fts WHERE rowid = old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, memory_id, content, reason, related_files)
    VALUES (new.rowid, new.id, new.content, coalesce(new.reason, ''), new.related_files);
END;
CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS memories_fts_update AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
    INSERT INTO memories_fts(rowid, memory_id, content, reason, related_files)
    VALUES (new.rowid, new.id, new.content, coalesce(new.reason, ''), new.related_files);
END;
"""


class ContextDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute(
            """INSERT INTO memories_fts(rowid, memory_id, content, reason, related_files)
               SELECT rowid, id, content, coalesce(reason, ''), related_files FROM memories
               WHERE rowid NOT IN (SELECT rowid FROM memories_fts)"""
        )
        self.connection.execute(
            """INSERT INTO events_fts(rowid, event_id, content)
               SELECT rowid, id, content FROM events
               WHERE rowid NOT IN (SELECT rowid FROM events_fts)"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def append_events(self, events: list[ContextEvent]) -> int:
        cursor = self.connection.executemany(
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
        return max(cursor.rowcount, 0)

    def append_memories(self, drafts: list[MemoryDraft], source_commit: str | None) -> int:
        rows = []
        for draft in drafts:
            identity = (
                f"{draft.source.agent}\0{draft.source.session_id}\0{draft.source.message_id}\0"
                f"{draft.type.value}\0{draft.content}"
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
        cursor = self.connection.executemany(
            """INSERT OR IGNORE INTO memories
               (id, type, content, reason, related_files, source_agent, source_session,
                source_message, source_path, source_commit, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self.connection.commit()
        return max(cursor.rowcount, 0)

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
        return [self._to_memory(row) for row in rows]

    def events(self, limit: int = 100) -> list[ContextEvent]:
        rows = self.connection.execute(
            "SELECT * FROM events ORDER BY occurred_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_event(row) for row in rows]

    def search_events(self, query: str, limit: int = 100) -> list[ContextEvent]:
        terms = list(dict.fromkeys(re.findall(r"[\w./-]{2,}", query.lower())))
        if not terms:
            return self.events(limit)
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        rows = self.connection.execute(
            """SELECT events.* FROM events_fts
               JOIN events ON events.rowid = events_fts.rowid
               WHERE events_fts MATCH ?
               ORDER BY bm25(events_fts), events.occurred_at DESC
               LIMIT ?""",
            (expression, limit),
        ).fetchall()
        if not rows:
            return self.events(limit)
        return [self._to_event(row) for row in rows]

    def search_memories(self, query: str, limit: int = 100) -> list[Memory]:
        terms = list(dict.fromkeys(re.findall(r"[\w./-]{2,}", query.lower())))
        if not terms:
            return self.memories()[:limit]
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        rows = self.connection.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY bm25(memories_fts), memories.created_at DESC
               LIMIT ?""",
            (expression, limit),
        ).fetchall()
        if not rows:
            return self.memories()[:limit]
        return [self._to_memory(row) for row in rows]

    @staticmethod
    def _to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
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

    @staticmethod
    def _to_event(row: sqlite3.Row) -> ContextEvent:
        return ContextEvent(
            id=row["id"],
            type=row["type"],
            occurred_at=row["occurred_at"],
            source=SourceRef(
                agent=row["source_agent"],
                session_id=row["source_session"],
                message_id=row["source_message"],
                path=Path(row["source_path"]),
            ),
            content=row["content"],
        )

    def mark_possibly_stale(self, memory_ids: list[str]) -> int:
        cursor = self.connection.executemany(
            "UPDATE memories SET status = 'possibly_stale' WHERE id = ? AND status = 'active'",
            [(memory_id,) for memory_id in memory_ids],
        )
        self.connection.commit()
        return max(cursor.rowcount, 0)

    def stats(self) -> dict[str, int]:
        def count(query: str) -> int:
            return int(self.connection.execute(query).fetchone()[0])

        return {
            "events": count("SELECT count(*) FROM events"),
            "memories": count("SELECT count(*) FROM memories"),
            "stale": count("SELECT count(*) FROM memories WHERE status = 'possibly_stale'"),
        }
