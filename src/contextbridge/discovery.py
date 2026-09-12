from __future__ import annotations

import os
from pathlib import Path


def default_session_root(source: str) -> Path:
    if source == "claude-code":
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        return config / "projects"
    if source == "codex":
        config = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return config / "sessions"
    raise ValueError(f"Unknown source: {source}")


def _mentions_project(path: Path, project: Path, max_bytes: int = 512_000) -> bool:
    """Check session metadata without loading an unbounded transcript into memory."""
    needles = {str(project), str(project.resolve())}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as session:
            metadata = session.read(max_bytes)
            return any(needle in metadata for needle in needles)
    except OSError:
        return False


def discover_sessions(
    source: str,
    project: Path,
    *,
    root: Path | None = None,
    limit: int = 1,
) -> list[Path]:
    """Return the newest agent sessions whose metadata references this project."""
    session_root = root or default_session_root(source)
    if limit <= 0 or not session_root.is_dir():
        return []
    candidates = [
        path
        for path in session_root.rglob("*.jsonl")
        if path.is_file() and _mentions_project(path, project)
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[:limit]
