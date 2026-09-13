from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .adapters.llm_extractor import LLMMemoryExtractor
from .app import create_registry, open_database
from .context_pack import build_context_pack
from .discovery import discover_sessions
from .git_state import current_commit, project_state, stale_memory_ids
from .llm import OpenAICompatibleClient
from .skill_install import install_agent_skills


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="contextbridge")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize local ContextBridge storage")

    sync = commands.add_parser("sync", help="Incrementally import a session")
    sync.add_argument("--source", required=True, choices=["claude-code", "codex"])
    sync.add_argument("--path", required=True, type=Path)
    sync.add_argument("--extractor", choices=["structured-notes", "llm"], default="structured-notes")
    sync.add_argument("--model", help="OpenAI-compatible model name; or CONTEXTBRIDGE_MODEL")
    sync.add_argument("--base-url", help="Provider API base URL; or CONTEXTBRIDGE_BASE_URL")

    capture = commands.add_parser(
        "capture", help="Discover sessions, sync them, and emit an agent-ready Context Pack"
    )
    capture.add_argument("--task", required=True)
    capture.add_argument("--source", choices=["auto", "claude-code", "codex"], default="auto")
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

    commands.add_parser("status", help="Show store and plugin status")
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
                source_names = ["claude-code", "codex"] if options.source == "auto" else [options.source]
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
            pack = build_context_pack(
                options.task,
                candidates,
                options.limit,
                options.token_budget,
                project_state(project),
            )
            rendered = registry.target("markdown").render(pack)
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
            pack = build_context_pack(
                options.task,
                candidates,
                options.limit,
                options.token_budget,
                project_state(project),
            )
            rendered = registry.target("markdown").render(pack)
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
