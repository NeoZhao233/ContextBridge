from __future__ import annotations

import subprocess
from pathlib import Path

from .models import Memory, ProjectState


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


def project_state(cwd: Path) -> ProjectState:
    status = _git(cwd, "status", "--short")
    recent = _git(cwd, "log", "-5", "--pretty=format:%h %s")
    return ProjectState(
        root=cwd,
        branch=_git(cwd, "branch", "--show-current"),
        commit=current_commit(cwd),
        changed_files=status.splitlines() if status else [],
        recent_commits=recent.splitlines() if recent else [],
    )


def stale_memory_ids(cwd: Path, memories: list[Memory]) -> list[str]:
    stale: list[str] = []
    for memory in memories:
        if not memory.source_commit or not memory.related_files:
            continue
        changed = _git(cwd, "diff", "--name-only", memory.source_commit, "--", *memory.related_files)
        if changed:
            stale.append(memory.id)
    return stale
