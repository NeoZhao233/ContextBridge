from __future__ import annotations

import subprocess
from pathlib import Path

from .models import Memory


def _git(cwd: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def current_commit(cwd: Path) -> str | None:
    return _git(cwd, "rev-parse", "HEAD")


def stale_memory_ids(cwd: Path, memories: list[Memory]) -> list[str]:
    stale: list[str] = []
    for memory in memories:
        if not memory.source_commit or not memory.related_files:
            continue
        changed = _git(cwd, "diff", "--name-only", memory.source_commit, "--", *memory.related_files)
        if changed:
            stale.append(memory.id)
    return stale
