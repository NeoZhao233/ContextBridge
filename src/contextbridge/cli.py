from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .adapters.llm_extractor import LLMMemoryExtractor
from .app import create_registry, open_database
from .context_pack import build_context_pack
from .discovery import discover_sessions
from .evaluation import evaluate_cases, load_cases, render_report
from .experiment import (
    create_plan,
    load_manifest,
    load_plan,
    load_runs,
    next_experiment_run,
    preflight_experiment,
    render_experiment_report,
    render_preflight,
    render_run_card,
    score_experiment,
    write_json,
)
from .fixture import create_experiment_fixture
from .git_state import current_commit, project_state, stale_memory_ids
from .llm import OpenAICompatibleClient
from .skill_install import install_agent_skills
from .validation import render_validation, validate_context_pack


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="contextbridge")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize local ContextBridge storage")

    sync = commands.add_parser("sync", help="Incrementally import a session")
    sync.add_argument("--source", required=True, choices=["claude-code", "codex", "dsh"])
    sync.add_argument("--path", required=True, type=Path)
    sync.add_argument("--extractor", choices=["structured-notes", "llm"], default="structured-notes")
    sync.add_argument("--model", help="OpenAI-compatible model name; or CONTEXTBRIDGE_MODEL")
    sync.add_argument("--base-url", help="Provider API base URL; or CONTEXTBRIDGE_BASE_URL")

    capture = commands.add_parser(
        "capture", help="Discover sessions, sync them, and emit an agent-ready Context Pack"
    )
    capture.add_argument("--task", required=True)
    capture.add_argument(
        "--source", choices=["auto", "claude-code", "codex", "dsh"], default="auto"
    )
    capture.add_argument("--path", action="append", type=Path, help="Explicit session JSONL path")
    capture.add_argument("--sessions-per-source", type=int, default=1)
    capture.add_argument("--extractor", choices=["structured-notes", "llm"], default="structured-notes")
    capture.add_argument("--model", help="OpenAI-compatible model name; or CONTEXTBRIDGE_MODEL")
    capture.add_argument("--base-url", help="Provider API base URL; or CONTEXTBRIDGE_BASE_URL")
    capture.add_argument("--limit", type=int, default=20)
    capture.add_argument("--token-budget", type=int, default=4000)
    capture.add_argument("--output", type=Path)

    install = commands.add_parser(
        "install-skills", help="Install handoff and resume skills for coding agents"
    )
    install.add_argument("--agent", choices=["all", "claude-code", "codex"], default="all")
    install.add_argument("--scope", choices=["project", "user"], default="project")
    install.add_argument("--force", action="store_true", help="Update existing skill files")

    evaluate = commands.add_parser("evaluate", help="Run the offline context retrieval benchmark")
    evaluate.add_argument("--dataset", type=Path, help="Evaluation dataset JSON")
    evaluate.add_argument("--format", choices=["markdown", "json"], default="markdown")
    evaluate.add_argument("--output", type=Path)

    experiment_plan = commands.add_parser(
        "experiment-plan", help="Create a seeded, balanced cross-agent experiment plan"
    )
    experiment_plan.add_argument("--manifest", required=True, type=Path)
    experiment_plan.add_argument("--output", required=True, type=Path)
    experiment_plan.add_argument("--seed", type=int, default=42)

    experiment_fixture = commands.add_parser(
        "experiment-fixture", help="Create a reproducible three-task experiment repository"
    )
    experiment_fixture.add_argument("--output", required=True, type=Path)
    experiment_fixture.add_argument("--manifest-output", type=Path)

    experiment_report = commands.add_parser(
        "experiment-report", help="Validate and aggregate cross-agent experiment results"
    )
    experiment_report.add_argument("--plan", required=True, type=Path)
    experiment_report.add_argument("--results", required=True, type=Path)
    experiment_report.add_argument("--format", choices=["markdown", "json"], default="markdown")
    experiment_report.add_argument("--output", type=Path)

    experiment_preflight = commands.add_parser(
        "experiment-preflight", help="Validate repositories and commits before agent runs"
    )
    experiment_preflight.add_argument("--plan", required=True, type=Path)
    experiment_preflight.add_argument("--format", choices=["text", "json"], default="text")

    experiment_next = commands.add_parser(
        "experiment-next", help="Show the next incomplete cross-agent experiment run"
    )
    experiment_next.add_argument("--plan", required=True, type=Path)
    experiment_next.add_argument("--results", type=Path)
    experiment_next.add_argument("--format", choices=["markdown", "json"], default="markdown")

    commands.add_parser("status", help="Show store and plugin status")
    validate = commands.add_parser("validate", help="Validate a generated Context Pack")
    validate.add_argument("--path", type=Path, default=Path(".contextbridge/handoff.md"))
    validate.add_argument("--token-budget", type=int, default=4000)
    validate.add_argument("--format", choices=["text", "json"], default="text")
    for name in ("inspect", "handoff"):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True)
        command.add_argument("--limit", type=int, default=20)
        command.add_argument("--token-budget", type=int, default=4000)
        if name == "handoff":
            command.add_argument("--output", type=Path)
    return root


def _llm_extractor(options: argparse.Namespace) -> LLMMemoryExtractor:
    api_key = os.environ.get("CONTEXTBRIDGE_API_KEY")
    model = options.model or os.environ.get("CONTEXTBRIDGE_MODEL")
    base_url = options.base_url or os.environ.get("CONTEXTBRIDGE_BASE_URL")
    if not api_key or not model or not base_url:
        raise SystemExit(
            "LLM extraction requires CONTEXTBRIDGE_API_KEY plus --model/CONTEXTBRIDGE_MODEL "
            "and --base-url/CONTEXTBRIDGE_BASE_URL"
        )
    return LLMMemoryExtractor(OpenAICompatibleClient(base_url, api_key, model))


def _sync_session(
    database,
    registry,
    source_name: str,
    path: Path,
    extractor_name: str,
    project: Path,
) -> tuple[int, int]:
    path = path.resolve()
    result = registry.source(source_name).sync(path, database.cursor(source_name, path))
    event_count = database.append_events(result.events)
    drafts = registry.extractor(extractor_name).extract(result.events)
    memory_count = database.append_memories(drafts, current_commit(project))
    database.set_cursor(source_name, path, result.cursor)
    return event_count, memory_count


def run(arguments: list[str] | None = None, cwd: Path | None = None) -> int:
    options = parser().parse_args(arguments)
    project = (cwd or Path.cwd()).resolve()
    if options.command == "install-skills":
        try:
            installed = install_agent_skills(options.agent, options.scope, project, force=options.force)
        except FileExistsError as error:
            raise SystemExit(str(error)) from error
        for path in installed:
            print(f"Installed {path}")
        return 0
    if options.command == "evaluate":
        report = evaluate_cases(load_cases(options.dataset))
        rendered = (
            render_report(report)
            if options.format == "markdown"
            else json.dumps(report.model_dump(), indent=2)
        )
        if options.output:
            output = options.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")
            print(f"Wrote evaluation report to {output}")
        else:
            print(rendered)
        return 0
    if options.command == "experiment-plan":
        plan = create_plan(load_manifest(options.manifest), options.seed)
        write_json(options.output.resolve(), plan)
        print(f"Wrote {len(plan.assignments)} experiment runs to {options.output.resolve()}")
        return 0
    if options.command == "experiment-fixture":
        try:
            repository, manifest, commit = create_experiment_fixture(
                options.output, options.manifest_output
            )
        except (FileExistsError, RuntimeError) as error:
            raise SystemExit(str(error)) from error
        print(f"Created fixture repository at {repository}")
        print(f"Pinned fixture commit: {commit}")
        print(f"Wrote experiment manifest to {manifest}")
        return 0
    if options.command == "experiment-report":
        report = score_experiment(load_plan(options.plan), load_runs(options.results))
        rendered = (
            render_experiment_report(report)
            if options.format == "markdown"
            else json.dumps(report.model_dump(mode="json"), indent=2)
        )
        if options.output:
            output = options.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")
            print(f"Wrote experiment report to {output}")
        else:
            print(rendered)
        return 0
    if options.command == "experiment-preflight":
        report = preflight_experiment(load_plan(options.plan))
        rendered = (
            json.dumps(report.model_dump(mode="json"), indent=2)
            if options.format == "json"
            else render_preflight(report)
        )
        print(rendered)
        return 0 if report.valid else 1
    if options.command == "experiment-next":
        runs = load_runs(options.results) if options.results else []
        card = next_experiment_run(load_plan(options.plan), runs)
        if card is None:
            print("All planned experiment runs are complete.")
            return 0
        rendered = (
            json.dumps(card.model_dump(mode="json"), indent=2)
            if options.format == "json"
            else render_run_card(card)
        )
        print(rendered)
        return 0
    if options.command == "validate":
        path = options.path.resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise SystemExit(f"Could not read Context Pack {path}: {error}") from error
        report = validate_context_pack(text, options.token_budget)
        print(render_validation(report, options.format))
        return 0 if report.valid else 1
    extra_extractor = None
    if options.command in ("sync", "capture") and options.extractor == "llm":
        extra_extractor = _llm_extractor(options)
    registry = create_registry(extra_extractor)
    database = open_database(project)
    try:
        if options.command == "init":
            print(f"Initialized {database.path}")
        elif options.command == "sync":
            event_count, memory_count = _sync_session(
                database, registry, options.source, options.path, options.extractor, project
            )
            print(f"Synced {event_count} events and {memory_count} memories from {options.source}.")
        elif options.command == "capture":
            if options.path and options.source == "auto":
                raise SystemExit("--path requires an explicit --source")
            sessions: list[tuple[str, Path]] = []
            if options.path:
                sessions = [(options.source, path) for path in options.path]
            else:
                source_names = (
                    ["claude-code", "codex", "dsh"]
                    if options.source == "auto"
                    else [options.source]
                )
                for source_name in source_names:
                    sessions.extend(
                        (source_name, path)
                        for path in discover_sessions(
                            source_name, project, limit=options.sessions_per_source
                        )
                    )
            if not sessions:
                raise SystemExit(
                    "No matching sessions found. Run from the project root or provide "
                    "--source and --path explicitly."
                )
            event_count = memory_count = 0
            for source_name, path in sessions:
                events, memories = _sync_session(
                    database, registry, source_name, path, options.extractor, project
                )
                event_count += events
                memory_count += memories
            database.mark_possibly_stale(stale_memory_ids(project, database.memories()))
            candidates = database.search_memories(options.task, max(100, options.limit * 5))
            excerpts = database.search_events(options.task, max(50, options.limit * 3))
            pack = build_context_pack(
                options.task,
                candidates,
                options.limit,
                options.token_budget,
                project_state(project),
                excerpts,
            )
            rendered = registry.target("markdown").render(pack)
            validation = validate_context_pack(rendered, options.token_budget)
            if not validation.valid:
                raise SystemExit(render_validation(validation))
            if options.output:
                output = options.output.resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered, encoding="utf-8")
                print(
                    f"Captured {event_count} events and {memory_count} memories from "
                    f"{len(sessions)} session(s); wrote {output}"
                )
            else:
                print(rendered)
        elif options.command == "status":
            database.mark_possibly_stale(stale_memory_ids(project, database.memories()))
            print(json.dumps({**database.stats(), "plugins": registry.describe()}, indent=2))
        else:
            database.mark_possibly_stale(stale_memory_ids(project, database.memories()))
            candidates = database.search_memories(options.task, max(100, options.limit * 5))
            excerpts = database.search_events(options.task, max(50, options.limit * 3))
            pack = build_context_pack(
                options.task,
                candidates,
                options.limit,
                options.token_budget,
                project_state(project),
                excerpts,
            )
            rendered = registry.target("markdown").render(pack)
            validation = validate_context_pack(rendered, options.token_budget)
            if not validation.valid:
                raise SystemExit(render_validation(validation))
            if options.command == "handoff" and options.output:
                output = options.output.resolve()
                output.write_text(rendered, encoding="utf-8")
                print(f"Wrote context pack to {output}")
            else:
                print(rendered)
        return 0
    finally:
        database.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
