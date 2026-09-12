from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contextbridge.adapters.extractors import StructuredNotesExtractor
from contextbridge.adapters.sources import ClaudeCodeSource
from contextbridge.context_pack import build_context_pack
from contextbridge.database import ContextDatabase
from contextbridge.models import Memory, MemoryType, SourceRef
from contextbridge.security import redact_secrets


class ContextBridgeTests(unittest.TestCase):
    def test_sync_is_incremental_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session.jsonl"
            records = [
                {"timestamp": "2026-01-01T00:00:00Z", "message": {"content": (
                    "DECISION: Use SQLite in src/store.py\n"
                    "DECISION: Keep the event log append-only"
                )}},
                {"timestamp": "2026-01-01T00:01:00Z", "message": {"content": "TODO: Add tests"}},
            ]
            session.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            source = ClaudeCodeSource()
            extractor = StructuredNotesExtractor()
            database = ContextDatabase(root / "data.db")
            try:
                first = source.sync(session)
                self.assertEqual(database.append_events(first.events), 2)
                self.assertEqual(database.append_memories(extractor.extract(first.events), None), 3)
                self.assertEqual(database.append_events(first.events), 0)
                self.assertEqual(source.sync(session, first.cursor).events, [])
            finally:
                database.close()

    def test_context_pack_ranks_relevant_open_loop(self) -> None:
        source = SourceRef(agent="codex", session_id="s1", message_id="1", path=Path("s.jsonl"))
        memories = [
            Memory(id="1", type=MemoryType.FACT, content="Uses SQLite", source=source),
            Memory(id="2", type=MemoryType.OPEN_LOOP, content="Add login integration test", source=source),
        ]
        pack = build_context_pack("add login test", memories, limit=1)
        self.assertEqual(pack.memories[0].id, "2")

    def test_redacts_common_secrets(self) -> None:
        self.assertEqual(redact_secrets("token=super-secret-value"), "token=[REDACTED]")
        self.assertIn("REDACTED_API_KEY", redact_secrets("sk-abcdefghijklmnopqrstuvwxyz"))


if __name__ == "__main__":
    unittest.main()
