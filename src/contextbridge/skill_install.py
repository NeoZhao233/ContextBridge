from __future__ import annotations

from importlib import resources
from pathlib import Path

SKILL_NAMES = ("contextbridge-handoff", "contextbridge-resume")
AGENT_SKILL_DIRS = {
    "codex": Path(".agents/skills"),
    "claude-code": Path(".claude/skills"),
}


def _copy_resource_tree(source, destination: Path, *, force: bool) -> None:
    destination.mkdir(parents=True, exist_ok=force)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target, force=force)
        else:
            if target.exists() and not force:
                raise FileExistsError(f"Skill file already exists: {target}")
            target.write_bytes(child.read_bytes())


def install_agent_skills(
    agent: str,
    scope: str,
    project: Path,
    *,
    user_home: Path | None = None,
    force: bool = False,
) -> list[Path]:
    agents = list(AGENT_SKILL_DIRS) if agent == "all" else [agent]
    unknown = [name for name in agents if name not in AGENT_SKILL_DIRS]
    if unknown:
        raise ValueError(f"Unknown agent: {unknown[0]}")
    if scope not in ("project", "user"):
        raise ValueError(f"Unknown scope: {scope}")

    base = project.resolve() if scope == "project" else (user_home or Path.home()).resolve()
    bundle = resources.files("contextbridge").joinpath("bundled_skills")
    destinations = [
        (skill_name, base / AGENT_SKILL_DIRS[agent_name] / skill_name)
        for agent_name in agents
        for skill_name in SKILL_NAMES
    ]
    if not force:
        existing = next((path for _, path in destinations if path.exists()), None)
        if existing is not None:
            raise FileExistsError(
                f"Skill already exists: {existing}. Re-run with --force to update it."
            )

    installed: list[Path] = []
    for skill_name, destination in destinations:
        _copy_resource_tree(bundle.joinpath(skill_name), destination, force=force)
        installed.append(destination)
    return installed
