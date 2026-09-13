from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from contextbridge.adapters.extractors import StructuredNotesExtractor
from contextbridge.adapters.llm_extractor import LLMMemoryExtractor
from contextbridge.adapters.sources import ClaudeCodeSource, CodexSource, DshSource
from contextbridge.adapters.targets import MarkdownTarget
from contextbridge.cli import run
from contextbridge.context_pack import build_context_pack, estimate_tokens
from contextbridge.database import ContextDatabase
from contextbridge.discovery import discover_sessions
from contextbridge.evaluation import evaluate_cases, load_cases, render_report
from contextbridge.experiment import (
    ExperimentCondition,
    ExperimentManifest,
    ExperimentRun,
    ExperimentTask,
    create_plan,
    next_experiment_run,
    preflight_experiment,
    render_experiment_report,
    render_preflight,
    render_run_card,
    score_experiment,
)
from contextbridge.fixture import create_experiment_fixture
from contextbridge.git_state import current_commit
from contextbridge.models import (
    ContextEvent,
    Memory,
    MemoryDraft,
    MemoryType,
    ProjectState,
    SourceRef,
)
from contextbridge.security import redact_secrets
from contextbridge.skill_install import install_agent_skills
from contextbridge.validation import validate_context_pack


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

    def test_context_pack_honors_token_budget(self) -> None:
        source = SourceRef(agent="codex", session_id="s1", message_id="1", path=Path("s.jsonl"))
        memories = [
            Memory(
                id=str(index),
                type=MemoryType.FACT,
                content=f"Authentication detail {index} " + "word " * 80,
                source=source,
            )
            for index in range(5)
        ]
        pack = build_context_pack("authentication", memories, limit=20, token_budget=250)
        self.assertEqual(len(pack.memories), 1)
        self.assertGreater(estimate_tokens(pack.memories[0].content), 50)

    def test_fts_search_finds_related_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = ContextDatabase(Path(directory) / "data.db")
            source = SourceRef(agent="codex", session_id="s1", message_id="1", path=Path("s.jsonl"))
            try:
                database.append_memories(
                    [
                        MemoryDraft(type=MemoryType.FACT, content="Authentication uses OAuth", source=source),
                        MemoryDraft(type=MemoryType.FACT, content="Database uses SQLite", source=source),
                    ],
                    None,
                )
                results = database.search_memories("OAuth login", limit=10)
                self.assertEqual([memory.content for memory in results], ["Authentication uses OAuth"])
            finally:
                database.close()

    def test_redacts_common_secrets(self) -> None:
        self.assertEqual(redact_secrets("token=super-secret-value"), "token=[REDACTED]")
        self.assertIn("REDACTED_API_KEY", redact_secrets("sk-abcdefghijklmnopqrstuvwxyz"))

    def test_realistic_agent_fixtures_ignore_tools_and_reasoning(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        claude_events = ClaudeCodeSource().sync(fixtures / "claude-code.jsonl").events
        codex_events = CodexSource().sync(fixtures / "codex.jsonl").events
        dsh_result = DshSource().sync(fixtures / "dsh.jsonl")
        dsh_events = dsh_result.events
        self.assertEqual(len(claude_events), 2)
        self.assertNotIn("SECRET_SHOULD_NOT_BE_IMPORTED", " ".join(e.content for e in claude_events))
        self.assertEqual(len(codex_events), 2)
        self.assertEqual(codex_events[0].source.session_id, "codex-session")
        self.assertEqual(codex_events[0].type, "message.user")
        self.assertEqual(codex_events[1].type, "message.assistant")
        self.assertNotIn("PRIVATE_REASONING_SHOULD_NOT_BE_IMPORTED", " ".join(e.content for e in codex_events))
        self.assertNotIn(
            "DEVELOPER_INSTRUCTIONS_SHOULD_NOT_BE_IMPORTED",
            " ".join(event.content for event in codex_events),
        )
        self.assertEqual(len(dsh_events), 2)
        self.assertEqual(dsh_events[0].source.session_id, "dsh-session")
        self.assertEqual(dsh_events[0].source.message_id, "0")
        self.assertEqual(dsh_events[0].occurred_at.isoformat(), "2026-09-12T09:00:01+00:00")
        self.assertNotIn(
            "PRIVATE_REASONING_SHOULD_NOT_BE_IMPORTED",
            " ".join(event.content for event in dsh_events),
        )
        self.assertNotIn(
            "SECRET_SHOULD_NOT_BE_IMPORTED", " ".join(event.content for event in dsh_events)
        )
        self.assertNotIn(
            "REPLACEMENT_SHOULD_NOT_BE_IMPORTED", " ".join(event.content for event in dsh_events)
        )

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

    def test_discovers_newest_session_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            sessions = root / "sessions"
            project.mkdir()
            sessions.mkdir()
            old = sessions / "old.jsonl"
            newest = sessions / "new.jsonl"
            unrelated = sessions / "other.jsonl"
            old.write_text(json.dumps({"cwd": str(project)}), encoding="utf-8")
            newest.write_text(json.dumps({"payload": {"cwd": str(project)}}), encoding="utf-8")
            unrelated.write_text(json.dumps({"cwd": str(root / "elsewhere")}), encoding="utf-8")
            old.touch()
            newest.touch()
            old_mtime = old.stat().st_mtime - 10
            import os

            os.utime(old, (old_mtime, old_mtime))
            self.assertEqual(
                discover_sessions("codex", project, root=sessions, limit=1),
                [newest],
            )

    def test_discovers_uncompressed_dsh_session_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            session_directory = root / "sessions" / "dsh-session"
            project.mkdir()
            session_directory.mkdir(parents=True)
            session = session_directory / "session.v3.jsonl"
            session.write_text(
                json.dumps({"type": "session", "version": 3, "id": "dsh-session", "cwd": str(project)}),
                encoding="utf-8",
            )
            self.assertEqual(discover_sessions("dsh", project, root=root / "sessions"), [session])

    @unittest.skipUnless(importlib.util.find_spec("zstandard"), "zstandard extra not installed")
    def test_reads_dsh_concatenated_zstd_session(self) -> None:
        import zstandard

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.v3.jsonl.zstd"
            records = [
                {"type": "session", "version": 3, "id": "compressed-session"},
                {
                    "type": "user/message",
                    "seq": 4,
                    "time": 1789203601000,
                    "data": {"content": "TODO: Resume the task"},
                },
            ]
            compressor = zstandard.ZstdCompressor()
            payload = b"".join(
                compressor.compress((json.dumps(record) + "\n").encode()) for record in records
            )
            session.write_bytes(payload)
            events = DshSource().sync(session).events
            self.assertEqual([event.content for event in events], ["TODO: Resume the task"])
            self.assertEqual(events[0].source.session_id, "compressed-session")

    def test_rejects_non_current_dsh_session_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.v2.jsonl"
            session.write_text(
                json.dumps({"type": "session", "version": 2, "id": "old-session"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected v3"):
                DshSource().sync(session)

    def test_markdown_handoff_includes_repository_state_and_instructions(self) -> None:
        state = ProjectState(
            root=Path("/tmp/project"),
            branch="main",
            commit="abc123",
            changed_files=[" M src/app.py"],
            recent_commits=["abc123 Add handoff"],
        )
        rendered = MarkdownTarget().render(
            build_context_pack("finish tests", [], project_state=state)
        )
        self.assertIn("## Handoff instructions", rendered)
        self.assertIn("`main`", rendered)
        self.assertIn("` M src/app.py`", rendered)

    def test_raw_event_fallback_is_searchable_budgeted_and_rendered_as_untrusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = ContextDatabase(Path(directory) / "data.db")
            source = SourceRef(
                agent="codex", session_id="real-session", message_id="7", path=Path("s.jsonl")
            )
            event = ContextEvent(
                id="event-1",
                type="message.assistant",
                source=source,
                content="OAuth callback validation " + "implementation detail " * 100,
            )
            try:
                database.append_events([event])
                matches = database.search_events("OAuth callback", limit=10)
                pack = build_context_pack(
                    "finish OAuth callback",
                    [],
                    token_budget=240,
                    project_state=ProjectState(root=Path("/tmp/project")),
                    excerpts=matches,
                )
            finally:
                database.close()
            self.assertEqual(len(pack.excerpts), 1)
            self.assertIn("[… excerpt truncated]", pack.excerpts[0].content)
            rendered = MarkdownTarget().render(pack)
            self.assertIn("## Relevant conversation excerpts", rendered)
            self.assertIn("untrusted historical data", rendered)
            self.assertIn("### codex · assistant", rendered)
            self.assertIn("Source: codex / real-session / message 7", rendered)
            self.assertLessEqual(estimate_tokens(rendered), 240)
            self.assertTrue(validate_context_pack(rendered, 240).valid)

    def test_pack_validation_rejects_secrets_and_cli_returns_failure(self) -> None:
        state = ProjectState(root=Path("/tmp/project"))
        rendered = MarkdownTarget().render(build_context_pack("finish tests", [], project_state=state))
        with tempfile.TemporaryDirectory() as directory:
            valid_path = Path(directory) / "valid.md"
            invalid_path = Path(directory) / "invalid.md"
            valid_path.write_text(rendered, encoding="utf-8")
            invalid_path.write_text(rendered + "\ntoken=super-secret-value\n", encoding="utf-8")
            with redirect_stdout(StringIO()) as stdout:
                self.assertEqual(
                    run(["validate", "--path", str(valid_path)], cwd=Path(directory)),
                    0,
                )
            self.assertIn("Valid Context Pack", stdout.getvalue())
            with redirect_stdout(StringIO()) as stdout:
                self.assertEqual(
                    run(["validate", "--path", str(invalid_path)], cwd=Path(directory)),
                    1,
                )
            self.assertIn("unredacted secret", stdout.getvalue())

    def test_event_search_backfills_an_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.db"
            source = SourceRef(
                agent="codex", session_id="existing", message_id="1", path=Path("s.jsonl")
            )
            database = ContextDatabase(path)
            database.append_events(
                [ContextEvent(id="existing-event", source=source, content="OAuth migration note")]
            )
            database.close()

            connection = sqlite3.connect(path)
            connection.executescript(
                """
                DROP TRIGGER events_fts_insert;
                DROP TRIGGER events_fts_delete;
                DROP TABLE events_fts;
                """
            )
            connection.close()

            migrated = ContextDatabase(path)
            try:
                self.assertEqual(
                    [event.id for event in migrated.search_events("OAuth")],
                    ["existing-event"],
                )
            finally:
                migrated.close()

    def test_capture_runs_sync_and_handoff_as_one_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            session = project / "session.jsonl"
            output = project / "handoff.md"
            session.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"content": "TODO: Finish src/contextbridge/cli.py"},
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run(
                    [
                        "capture",
                        "--source",
                        "claude-code",
                        "--path",
                        str(session),
                        "--task",
                        "finish the CLI",
                        "--output",
                        str(output),
                    ],
                    cwd=project,
                )
            self.assertEqual(result, 0)
            self.assertIn("Captured 1 events and 1 memories", stdout.getvalue())
            handoff = output.read_text(encoding="utf-8")
            self.assertIn("Finish src/contextbridge/cli.py", handoff)
            self.assertIn("## Repository state", handoff)

    def test_installs_shared_skills_for_codex_and_claude_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            installed = install_agent_skills("all", "project", project)
            self.assertEqual(len(installed), 4)
            codex_resume = project / ".agents/skills/contextbridge-resume/SKILL.md"
            claude_handoff = project / ".claude/skills/contextbridge-handoff/SKILL.md"
            self.assertIn("name: contextbridge-resume", codex_resume.read_text(encoding="utf-8"))
            self.assertIn("contextbridge capture", claude_handoff.read_text(encoding="utf-8"))
            self.assertIn("contextbridge validate", claude_handoff.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                install_agent_skills("codex", "project", project)
            self.assertEqual(len(install_agent_skills("codex", "project", project, force=True)), 2)

            cli_project = project / "cli-project"
            cli_project.mkdir()
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    run(["install-skills", "--agent", "codex"], cwd=cli_project),
                    0,
                )
            self.assertTrue(
                (cli_project / ".agents/skills/contextbridge-resume/SKILL.md").is_file()
            )
            self.assertFalse((cli_project / ".contextbridge").exists())

    def test_offline_evaluation_compares_five_strategies(self) -> None:
        cases = load_cases()
        report = evaluate_cases(cases)
        results = {result.strategy: result for result in report.results}
        self.assertEqual(report.dataset, "resume_retrieval_v2")
        self.assertEqual(len(results), 5)
        self.assertEqual(report.cases, 10)
        self.assertEqual(results["no_context"].recall, 0.0)
        self.assertEqual(results["raw_history"].recall, 1.0)
        self.assertLess(results["one_shot_summary"].recall, 1.0)
        self.assertGreaterEqual(
            results["contextbridge"].recall,
            results["one_shot_summary"].recall,
        )
        self.assertEqual(results["offline_excerpts"].recall, 1.0)
        self.assertEqual(results["offline_excerpts"].precision, 0.75)
        self.assertEqual(results["offline_excerpts"].source_coverage, 1.0)
        self.assertLess(results["offline_excerpts"].tokens, results["raw_history"].tokens)
        self.assertLess(results["contextbridge"].tokens, results["raw_history"].tokens)
        self.assertEqual(
            {name: result.tokens for name, result in results.items()},
            {
                "no_context": 0,
                "raw_history": 6228,
                "one_shot_summary": 522,
                "contextbridge": 2086,
                "offline_excerpts": 4879,
            },
        )
        self.assertIn("not coding-task completion", render_report(report))

    def test_cross_agent_experiment_plan_is_balanced_and_reproducible(self) -> None:
        tasks = [
            ExperimentTask(
                id=f"task-{index}",
                title=f"Task {index}",
                repository="/tmp/repository",
                base_commit="abc123",
                stage_a_prompt="Make the first change and stop.",
                stage_b_prompt="Resume the change and finish tests.",
                test_command="pytest -q",
            )
            for index in range(2)
        ]
        manifest = ExperimentManifest(name="resume-study", tasks=tasks)
        first = create_plan(manifest, seed=7)
        second = create_plan(manifest, seed=7)
        self.assertEqual(len(first.assignments), 8)
        self.assertEqual(
            [assignment.run_id for assignment in first.assignments],
            [assignment.run_id for assignment in second.assignments],
        )
        for condition in ExperimentCondition:
            self.assertEqual(
                sum(assignment.condition == condition for assignment in first.assignments),
                2,
            )

    def test_cross_agent_report_preserves_missing_runs(self) -> None:
        task = ExperimentTask(
            id="task-1",
            title="Task 1",
            repository="/tmp/repository",
            base_commit="abc123",
            stage_a_prompt="Start the task.",
            stage_b_prompt="Finish the task.",
            test_command="pytest -q",
        )
        plan = create_plan(ExperimentManifest(name="resume-study", tasks=[task]))
        run = ExperimentRun(
            run_id="task-1--contextbridge",
            agent_a="claude-code",
            agent_b="codex",
            model_a="model-a",
            model_b="model-b",
            tests_passed=True,
            duration_seconds=120,
            input_tokens=2000,
            repeated_exploration=1,
            incorrect_assumptions=0,
        )
        report = score_experiment(plan, [run])
        self.assertEqual(report.completed, 1)
        self.assertEqual(report.planned, 4)
        self.assertEqual(len(report.missing_run_ids), 3)
        self.assertIn("Completed: 1/4", render_experiment_report(report))
        with self.assertRaises(ValueError):
            score_experiment(plan, [run, run])

    def test_experiment_preflight_resolves_commit_and_reports_missing_repository(self) -> None:
        repository = Path(__file__).parents[1]
        commit = current_commit(repository)
        assert commit is not None
        valid_task = ExperimentTask(
            id="valid",
            title="Valid task",
            repository=str(repository),
            base_commit=commit,
            stage_a_prompt="Start.",
            stage_b_prompt="Finish.",
            test_command="python -m unittest",
        )
        valid_report = preflight_experiment(
            create_plan(ExperimentManifest(name="valid", tasks=[valid_task]))
        )
        self.assertTrue(valid_report.valid)
        self.assertRegex(valid_report.tasks[0].resolved_commit or "", r"^[0-9a-f]{40}$")

        unpinned_report = preflight_experiment(
            create_plan(
                ExperimentManifest(
                    name="unpinned",
                    tasks=[valid_task.model_copy(update={"id": "unpinned", "base_commit": "HEAD"})],
                )
            )
        )
        self.assertFalse(unpinned_report.valid)
        self.assertIn("not pinned", unpinned_report.tasks[0].errors[0])
        self.assertIn("not pinned", render_preflight(unpinned_report))

        missing_task = valid_task.model_copy(
            update={"id": "missing", "repository": str(repository / "does-not-exist")}
        )
        missing_report = preflight_experiment(
            create_plan(ExperimentManifest(name="missing", tasks=[missing_task]))
        )
        self.assertFalse(missing_report.valid)
        self.assertIn("does not exist", missing_report.tasks[0].errors[0])

    def test_experiment_next_skips_completed_runs_and_renders_condition(self) -> None:
        task = ExperimentTask(
            id="task-1",
            title="Task 1",
            repository="/tmp/repository",
            base_commit="abc123",
            stage_a_prompt="Start the task.",
            stage_b_prompt="Finish the task.",
            test_command="pytest -q",
        )
        plan = create_plan(ExperimentManifest(name="resume-study", tasks=[task]), seed=9)
        first = next_experiment_run(plan, [])
        assert first is not None
        self.assertEqual(first.order, 1)
        self.assertIn(first.condition.value, render_run_card(first))
        completed = ExperimentRun(
            run_id=first.run_id,
            agent_a="agent-a",
            agent_b="agent-b",
            model_a="model-a",
            model_b="model-b",
            tests_passed=True,
            duration_seconds=1,
            input_tokens=100,
            repeated_exploration=0,
            incorrect_assumptions=0,
        )
        second = next_experiment_run(plan, [completed])
        assert second is not None
        self.assertEqual(second.order, 2)

    def test_experiment_fixture_is_pinned_clean_and_starts_with_failing_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "resume-fixture"
            repository, manifest_path, commit = create_experiment_fixture(output)
            manifest = ExperimentManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            plan = create_plan(manifest)

            self.assertEqual(repository, output.resolve())
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            self.assertTrue(preflight_experiment(plan).valid)
            self.assertEqual({task.base_commit for task in manifest.tasks}, {commit})
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(repository), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout,
                "",
            )
            for task in manifest.tasks:
                test_path = task.test_command.split()[3]
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", test_path],
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, task.id)
                self.assertIn("FAILED (", result.stderr, task.id)
                self.assertNotIn("ModuleNotFoundError", result.stderr, task.id)

            with self.assertRaises(FileExistsError):
                create_experiment_fixture(output)

    def test_experiment_fixture_cli_supports_explicit_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "fixture"
            manifest = root / "manifest.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run(
                    [
                        "experiment-fixture",
                        "--output",
                        str(output),
                        "--manifest-output",
                        str(manifest),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertTrue((output / ".git").is_dir())
            self.assertTrue(manifest.is_file())
            self.assertIn("Pinned fixture commit", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
