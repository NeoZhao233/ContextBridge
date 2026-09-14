from __future__ import annotations

import json
import random
import re
import subprocess
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, Field

from .models import utc_now


class ExperimentCondition(StrEnum):
    NO_CONTEXT = "no_context"
    RAW_HISTORY = "raw_history"
    ONE_SHOT_SUMMARY = "one_shot_summary"
    CONTEXTBRIDGE = "contextbridge"


class ExperimentTask(BaseModel):
    id: str
    title: str
    repository: str
    base_commit: str
    stage_a_prompt: str
    stage_b_prompt: str
    test_command: str


class ExperimentManifest(BaseModel):
    name: str
    tasks: list[ExperimentTask]


class ExperimentAssignment(BaseModel):
    order: int
    run_id: str
    task_id: str
    condition: ExperimentCondition


class ExperimentPlan(BaseModel):
    schema_version: int = 1
    name: str
    seed: int
    created_at: datetime = Field(default_factory=utc_now)
    tasks: list[ExperimentTask]
    assignments: list[ExperimentAssignment]


class ExperimentRun(BaseModel):
    run_id: str
    agent_a: str
    agent_b: str
    model_a: str
    model_b: str
    tests_passed: bool
    duration_seconds: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    repeated_exploration: int = Field(ge=0)
    incorrect_assumptions: int = Field(ge=0)
    trace_path: str | None = None
    notes: str | None = None


class ExperimentCheckpoint(BaseModel):
    task_id: str
    commit: str
    agent_a: str
    model_a: str
    transcript_path: str
    summary_path: str
    context_pack_path: str


class ConditionScore(BaseModel):
    condition: ExperimentCondition
    completed: int
    planned: int
    pass_rate: float | None
    average_duration_seconds: float | None
    average_input_tokens: float | None
    average_repeated_exploration: float | None
    average_incorrect_assumptions: float | None


class ExperimentReport(BaseModel):
    name: str
    completed: int
    planned: int
    missing_run_ids: list[str]
    scores: list[ConditionScore]


class ExperimentPreflightTask(BaseModel):
    task_id: str
    repository: str
    requested_commit: str
    resolved_commit: str | None = None
    errors: list[str] = Field(default_factory=list)


class ExperimentPreflightReport(BaseModel):
    valid: bool
    tasks: list[ExperimentPreflightTask]


class ExperimentRunCard(BaseModel):
    order: int
    run_id: str
    condition: ExperimentCondition
    repository: str
    base_commit: str
    stage_a_prompt: str
    stage_b_prompt: str
    test_command: str
    condition_payload: str
    stage_a_checkpoint: str | None = None


def load_manifest(path: Path) -> ExperimentManifest:
    return ExperimentManifest.model_validate_json(path.read_text(encoding="utf-8"))


def create_plan(manifest: ExperimentManifest, seed: int = 42) -> ExperimentPlan:
    if not manifest.tasks:
        raise ValueError("Experiment manifest must contain at least one task")
    task_ids = [task.id for task in manifest.tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Experiment task IDs must be unique")

    assignments = [
        ExperimentAssignment(
            order=0,
            run_id=f"{task.id}--{condition.value}",
            task_id=task.id,
            condition=condition,
        )
        for task in manifest.tasks
        for condition in ExperimentCondition
    ]
    random.Random(seed).shuffle(assignments)
    for order, assignment in enumerate(assignments, start=1):
        assignment.order = order
    return ExperimentPlan(
        name=manifest.name,
        seed=seed,
        tasks=manifest.tasks,
        assignments=assignments,
    )


def load_plan(path: Path) -> ExperimentPlan:
    return ExperimentPlan.model_validate_json(path.read_text(encoding="utf-8"))


def load_runs(path: Path) -> list[ExperimentRun]:
    runs = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            runs.append(ExperimentRun.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"Invalid result at line {line_number}: {error}") from error
    return runs


def load_checkpoints(path: Path) -> list[ExperimentCheckpoint]:
    checkpoints = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            checkpoints.append(ExperimentCheckpoint.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"Invalid checkpoint at line {line_number}: {error}") from error
    return checkpoints


def _git_commit(repository: Path, commit: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def validate_checkpoint(plan: ExperimentPlan, checkpoint: ExperimentCheckpoint) -> None:
    tasks = {task.id: task for task in plan.tasks}
    if checkpoint.task_id not in tasks:
        raise ValueError(f"Checkpoint references unknown task: {checkpoint.task_id}")
    task = tasks[checkpoint.task_id]
    repository = Path(task.repository).expanduser().resolve()
    resolved = _git_commit(repository, checkpoint.commit)
    if resolved is None:
        raise ValueError(f"Checkpoint commit does not resolve: {checkpoint.commit}")
    if resolved != checkpoint.commit:
        raise ValueError(f"Checkpoint commit must be a full object ID: {resolved}")
    ancestor = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", task.base_commit, resolved],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("Checkpoint commit must descend from the task base commit")
    for label, value in (
        ("transcript", checkpoint.transcript_path),
        ("summary", checkpoint.summary_path),
        ("Context Pack", checkpoint.context_pack_path),
    ):
        if not Path(value).expanduser().resolve().is_file():
            raise ValueError(f"Checkpoint {label} does not exist: {value}")


def record_checkpoint(
    plan: ExperimentPlan,
    checkpoint: ExperimentCheckpoint,
    output: Path,
) -> Path:
    validate_checkpoint(plan, checkpoint)
    path = output.expanduser().resolve()
    existing = load_checkpoints(path) if path.exists() else []
    if checkpoint.task_id in {item.task_id for item in existing}:
        raise ValueError(f"Checkpoint already recorded for task: {checkpoint.task_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(checkpoint.model_dump_json() + "\n")
    return path


def preflight_experiment(plan: ExperimentPlan) -> ExperimentPreflightReport:
    reports: list[ExperimentPreflightTask] = []
    for task in plan.tasks:
        repository = Path(task.repository).expanduser().resolve()
        errors: list[str] = []
        resolved_commit = None
        if not repository.is_dir():
            errors.append("repository directory does not exist")
        else:
            result = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "--verify", f"{task.base_commit}^{{commit}}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                errors.append("base commit does not resolve in repository")
            else:
                resolved_commit = result.stdout.strip()
                if task.base_commit != resolved_commit:
                    errors.append(
                        "base commit is not pinned to its full object ID; "
                        f"replace it with {resolved_commit}"
                    )
        reports.append(
            ExperimentPreflightTask(
                task_id=task.id,
                repository=str(repository),
                requested_commit=task.base_commit,
                resolved_commit=resolved_commit,
                errors=errors,
            )
        )
    return ExperimentPreflightReport(
        valid=all(not report.errors for report in reports),
        tasks=reports,
    )


CONDITION_PAYLOADS = {
    ExperimentCondition.NO_CONTEXT: (
        "Provide Agent B only the stage-B prompt and repository state. Do not provide Agent A history."
    ),
    ExperimentCondition.RAW_HISTORY: (
        "Provide Agent B the complete permitted Agent A transcript without summarization."
    ),
    ExperimentCondition.ONE_SHOT_SUMMARY: (
        "Provide Agent B only the summary produced by the pinned summary model and prompt."
    ),
    ExperimentCondition.CONTEXTBRIDGE: (
        "Run ContextBridge capture after Agent A, validate the pack, and provide only that pack to Agent B."
    ),
}


def next_experiment_run(
    plan: ExperimentPlan, runs: list[ExperimentRun]
) -> ExperimentRunCard | None:
    score_experiment(plan, runs)
    completed = {run.run_id for run in runs}
    tasks = {task.id: task for task in plan.tasks}
    assignment = next(
        (
            candidate
            for candidate in sorted(plan.assignments, key=lambda item: item.order)
            if candidate.run_id not in completed
        ),
        None,
    )
    if assignment is None:
        return None
    task = tasks[assignment.task_id]
    return ExperimentRunCard(
        order=assignment.order,
        run_id=assignment.run_id,
        condition=assignment.condition,
        repository=task.repository,
        base_commit=task.base_commit,
        stage_a_prompt=task.stage_a_prompt,
        stage_b_prompt=task.stage_b_prompt,
        test_command=task.test_command,
        condition_payload=CONDITION_PAYLOADS[assignment.condition],
    )


def prepare_experiment_run(
    plan: ExperimentPlan,
    runs: list[ExperimentRun],
    worktree_root: Path,
    checkpoints: list[ExperimentCheckpoint] | None = None,
) -> tuple[ExperimentRunCard, Path] | None:
    preflight = preflight_experiment(plan)
    if not preflight.valid:
        errors = [
            f"{task.task_id}: {error}"
            for task in preflight.tasks
            for error in task.errors
        ]
        raise ValueError(f"Experiment preflight failed: {'; '.join(errors)}")

    card = next_experiment_run(plan, runs)
    if card is None:
        return None

    repository = Path(card.repository).expanduser().resolve()
    checkpoint = None
    starting_commit = card.base_commit
    if checkpoints is not None:
        checkpoint_ids = [item.task_id for item in checkpoints]
        if len(checkpoint_ids) != len(set(checkpoint_ids)):
            raise ValueError("Experiment checkpoints contain duplicate task IDs")
        task_id = card.run_id.rsplit("--", 1)[0]
        checkpoint = next((item for item in checkpoints if item.task_id == task_id), None)
        if checkpoint is None:
            raise ValueError(f"No Stage-A checkpoint recorded for task: {task_id}")
        validate_checkpoint(plan, checkpoint)
        starting_commit = checkpoint.commit
    root = worktree_root.expanduser().resolve()
    try:
        root.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Worktree root must be outside the fixture repository")

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", card.run_id).strip("-.") or "run"
    digest = sha256(card.run_id.encode()).hexdigest()[:8]
    destination = root / f"{card.order:02d}-{slug[:48]}-{digest}"
    if destination.exists():
        raise FileExistsError(f"Experiment worktree already exists: {destination}")
    root.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--detach",
            str(destination),
            starting_commit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(f"Could not prepare experiment worktree: {detail}")
    card_updates: dict[str, str] = {"repository": str(destination)}
    if checkpoint is not None:
        if card.condition == ExperimentCondition.NO_CONTEXT:
            payload = "Provide Agent B only the stage-B prompt and checkpoint repository state."
        else:
            source = {
                ExperimentCondition.RAW_HISTORY: checkpoint.transcript_path,
                ExperimentCondition.ONE_SHOT_SUMMARY: checkpoint.summary_path,
                ExperimentCondition.CONTEXTBRIDGE: checkpoint.context_pack_path,
            }[card.condition]
            input_directory = destination / ".contextbridge"
            input_directory.mkdir(parents=True, exist_ok=True)
            condition_input = input_directory / "condition.md"
            condition_input.write_bytes(Path(source).expanduser().resolve().read_bytes())
            payload = (
                f"Provide Agent B only `.contextbridge/condition.md` as the "
                f"{card.condition.value} handoff input."
            )
        card_updates.update(
            {
                "condition_payload": payload,
                "stage_a_checkpoint": starting_commit,
            }
        )
    prepared_card = card.model_copy(update=card_updates)
    return prepared_card, destination


def render_run_card(card: ExperimentRunCard) -> str:
    stage_a = (
        [
            "## Agent A checkpoint",
            "",
            f"Reuse `{card.stage_a_checkpoint}`. Do not rerun Agent A.",
        ]
        if card.stage_a_checkpoint
        else ["## Agent A", "", card.stage_a_prompt]
    )
    return "\n".join(
        [
            f"# Experiment run {card.order}: {card.run_id}",
            "",
            f"- Condition: `{card.condition.value}`",
            f"- Repository: `{card.repository}`",
            f"- Base commit: `{card.base_commit}`",
            *(
                [f"- Stage-A checkpoint: `{card.stage_a_checkpoint}`"]
                if card.stage_a_checkpoint
                else []
            ),
            f"- Test command: `{card.test_command}`",
            "",
            *stage_a,
            "",
            "## Condition payload",
            "",
            card.condition_payload,
            "",
            "## Agent B",
            "",
            card.stage_b_prompt,
            "",
        ]
    )


def render_preflight(report: ExperimentPreflightReport) -> str:
    output = ["Experiment preflight passed" if report.valid else "Experiment preflight failed"]
    for task in report.tasks:
        status = "; ".join(task.errors) if task.errors else task.resolved_commit or "unresolved"
        output.append(f"- {task.task_id}: {status}")
    return "\n".join(output)


def _average(values: list[float | int]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def score_experiment(plan: ExperimentPlan, runs: list[ExperimentRun]) -> ExperimentReport:
    assignments = {assignment.run_id: assignment for assignment in plan.assignments}
    if len(assignments) != len(plan.assignments):
        raise ValueError("Experiment plan contains duplicate run IDs")
    run_ids = [run.run_id for run in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("Experiment results contain duplicate run IDs")
    unknown = sorted(set(run_ids) - set(assignments))
    if unknown:
        raise ValueError(f"Results contain unknown run IDs: {', '.join(unknown)}")

    scores = []
    for condition in ExperimentCondition:
        planned_ids = {
            assignment.run_id
            for assignment in plan.assignments
            if assignment.condition == condition
        }
        condition_runs = [run for run in runs if run.run_id in planned_ids]
        scores.append(
            ConditionScore(
                condition=condition,
                completed=len(condition_runs),
                planned=len(planned_ids),
                pass_rate=(
                    round(sum(run.tests_passed for run in condition_runs) / len(condition_runs), 6)
                    if condition_runs
                    else None
                ),
                average_duration_seconds=_average(
                    [run.duration_seconds for run in condition_runs]
                ),
                average_input_tokens=_average([run.input_tokens for run in condition_runs]),
                average_repeated_exploration=_average(
                    [run.repeated_exploration for run in condition_runs]
                ),
                average_incorrect_assumptions=_average(
                    [run.incorrect_assumptions for run in condition_runs]
                ),
            )
        )
    return ExperimentReport(
        name=plan.name,
        completed=len(runs),
        planned=len(plan.assignments),
        missing_run_ids=sorted(set(assignments) - set(run_ids)),
        scores=scores,
    )


def render_experiment_report(report: ExperimentReport) -> str:
    def value(number: float | None, suffix: str = "") -> str:
        return "—" if number is None else f"{number:.1f}{suffix}"

    output = [
        f"# Experiment report: {report.name}",
        "",
        f"Completed: {report.completed}/{report.planned}",
        "",
        "| Condition | Runs | Test pass | Seconds | Input tokens | Re-exploration | Wrong assumptions |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for score in report.scores:
        pass_rate = "—" if score.pass_rate is None else f"{score.pass_rate:.1%}"
        output.append(
            f"| {score.condition.value} | {score.completed}/{score.planned} | {pass_rate} | "
            f"{value(score.average_duration_seconds)} | {value(score.average_input_tokens)} | "
            f"{value(score.average_repeated_exploration)} | "
            f"{value(score.average_incorrect_assumptions)} |"
        )
    if report.missing_run_ids:
        output.extend(["", f"Missing runs: {', '.join(report.missing_run_ids)}"])
    output.extend(
        [
            "",
            "Incomplete conditions are reported, not imputed. Interpret small samples descriptively.",
            "",
        ]
    )
    return "\n".join(output)


def write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
