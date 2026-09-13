from __future__ import annotations

import os
from pathlib import Path

from .adapters.sources import read_session_text


def default_session_root(source: str) -> Path | None:
    if source == "claude-code":
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        return config / "projects"
    if source == "codex":
        config = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return config / "sessions"
    if source == "dsh":
        configured = os.environ.get("CONTEXTBRIDGE_DSH_SESSION_ROOT")
        return Path(configured).expanduser() if configured else None
    raise ValueError(f"Unknown source: {source}")


def _mentions_project(path: Path, project: Path, max_bytes: int = 512_000) -> bool:
    """Check session metadata without loading an unbounded transcript into memory."""
    needles = {str(project), str(project.resolve())}
    try:
        metadata = read_session_text(path, max_bytes)
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
    session_root = root if root is not None else default_session_root(source)
    if limit <= 0 or session_root is None or not session_root.is_dir():
        return []
    patterns = (
        ("session.v3.jsonl", "session.v3.jsonl.zstd")
        if source == "dsh"
        else ("*.jsonl",)
    )
    candidates = [
        path
        for pattern in patterns
        for path in session_root.rglob(pattern)
        if path.is_file() and _mentions_project(path, project)
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[:limit]
