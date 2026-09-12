from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contextbridge.adapters.extractors import StructuredNotesExtractor
from contextbridge.adapters.llm_extractor import LLMMemoryExtractor
from contextbridge.adapters.sources import ClaudeCodeSource, CodexSource
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

    def test_realistic_agent_fixtures_ignore_tools_and_reasoning(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        claude_events = ClaudeCodeSource().sync(fixtures / "claude-code.jsonl").events
        codex_events = CodexSource().sync(fixtures / "codex.jsonl").events
        self.assertEqual(len(claude_events), 2)
        self.assertNotIn("SECRET_SHOULD_NOT_BE_IMPORTED", " ".join(e.content for e in claude_events))
        self.assertEqual(len(codex_events), 2)
        self.assertNotIn("PRIVATE_REASONING_SHOULD_NOT_BE_IMPORTED", " ".join(e.content for e in codex_events))

    def test_llm_extractor_validates_sources_paths_and_redacts_prompt(self) -> None:
        event = ClaudeCodeSource().sync(Path(__file__).parent / "fixtures" / "claude-code.jsonl").events[0]

        class FakeClient:
            prompt = ""

            def complete(self, system: str, user: str) -> str:
                self.prompt = user
                return json.dumps([
                    {
                        "event_id": event.id,
                        "type": "decision",
                        "content": "Use SQLite for local persistence",
                        "reason": "The MVP is local-first",
                        "related_files": ["src/contextbridge/database.py", "../outside.txt"],
                    },
                    {
                        "event_id": "invented-event",
                        "type": "fact",
                        "content": "This must be dropped",
                        "reason": None,
                        "related_files": [],
                    },
                ])

        client = FakeClient()
        event.content += " API_KEY=super-secret-value"
        memories = LLMMemoryExtractor(client).extract([event])
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].source, event.source)
        self.assertEqual(memories[0].related_files, ["src/contextbridge/database.py"])
        self.assertNotIn("super-secret-value", client.prompt)


if __name__ == "__main__":
    unittest.main()
