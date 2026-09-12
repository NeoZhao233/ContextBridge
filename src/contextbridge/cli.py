from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import create_registry, open_database
from .context_pack import build_context_pack
from .git_state import current_commit, stale_memory_ids


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="contextbridge")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize local ContextBridge storage")

    sync = commands.add_parser("sync", help="Incrementally import a session")
    sync.add_argument("--source", required=True, choices=["claude-code", "codex"])
    sync.add_argument("--path", required=True, type=Path)

    commands.add_parser("status", help="Show store and plugin status")
    for name in ("inspect", "handoff"):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True)
        command.add_argument("--limit", type=int, default=20)
        if name == "handoff":
            command.add_argument("--output", type=Path)
    return root


def run(arguments: list[str] | None = None, cwd: Path | None = None) -> int:
    options = parser().parse_args(arguments)
    project = (cwd or Path.cwd()).resolve()
    registry = create_registry()
    database = open_database(project)
    try:
        if options.command == "init":
            print(f"Initialized {database.path}")
        elif options.command == "sync":
            path = options.path.resolve()
            source = registry.source(options.source)
            result = source.sync(path, database.cursor(options.source, path))
            event_count = database.append_events(result.events)
            drafts = registry.extractor("structured-notes").extract(result.events)
            memory_count = database.append_memories(drafts, current_commit(project))
            database.set_cursor(options.source, path, result.cursor)
            print(f"Synced {event_count} events and {memory_count} memories from {options.source}.")
        elif options.command == "status":
            database.mark_possibly_stale(stale_memory_ids(project, database.memories()))
            print(json.dumps({**database.stats(), "plugins": registry.describe()}, indent=2))
        else:
            database.mark_possibly_stale(stale_memory_ids(project, database.memories()))
            pack = build_context_pack(options.task, database.memories(), options.limit)
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
