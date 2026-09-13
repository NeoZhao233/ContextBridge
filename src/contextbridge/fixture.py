from __future__ import annotations

import json
import subprocess
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .experiment import ExperimentManifest, write_json


def _copy_fixture(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name == "tasks.template.json" or child.name == "__pycache__":
            continue
        target = destination / child.name
        if child.is_dir():
            _copy_fixture(child, target)
        else:
            target.write_bytes(child.read_bytes())


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def create_experiment_fixture(
    output: Path, manifest_output: Path | None = None
) -> tuple[Path, Path, str]:
    repository = output.expanduser().resolve()
    manifest_path = (
        manifest_output.expanduser().resolve()
        if manifest_output
        else repository.parent / f"{repository.name}.tasks.json"
    )
    if repository.exists():
        raise FileExistsError(f"Fixture output already exists: {repository}")
    if manifest_path.exists():
        raise FileExistsError(f"Fixture manifest already exists: {manifest_path}")

    fixture = resources.files("contextbridge").joinpath("experiment_fixture")
    _copy_fixture(fixture, repository)
    _git(repository, "init", "-q")
    _git(repository, "add", ".")
    _git(
        repository,
        "-c",
        "user.name=ContextBridge",
        "-c",
        "user.email=contextbridge@example.invalid",
        "commit",
        "-q",
        "-m",
        "Create resume experiment fixture",
    )
    commit = _git(repository, "rev-parse", "HEAD")

    template = fixture.joinpath("tasks.template.json").read_text(encoding="utf-8")
    rendered = template.replace("__REPOSITORY__", str(repository)).replace(
        "__BASE_COMMIT__", commit
    )
    manifest = ExperimentManifest.model_validate(json.loads(rendered))
    write_json(manifest_path, manifest)
    return repository, manifest_path, commit
