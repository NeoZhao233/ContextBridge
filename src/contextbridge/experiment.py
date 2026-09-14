from __future__ import annotations

import json
import random
import re
import shlex
import subprocess
import sys
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

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
    evaluation_command: str | None = None
    evaluation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
    raw_input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    trace_sha256: str | None = None
    test_exit_code: int | None = None
    test_output_path: str | None = None
    test_output_sha256: str | None = None
    diff_path: str | None = None
    diff_sha256: str | None = None
    assertions_passed: int | None = Field(default=None, ge=0)
    assertions_total: int | None = Field(default=None, ge=1)
    decision_checks_passed: int | None = Field(default=None, ge=0)
    decision_checks_total: int | None = Field(default=None, ge=0)
    regressions: int | None = Field(default=None, ge=0)
    evaluation_exit_code: int | None = None
    evaluation_output_path: str | None = None
    evaluation_output_sha256: str | None = None
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
    average_task_completion_rate: float | None
    average_decision_adherence_rate: float | None
    average_regressions: float | None


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


class CodexTraceUsage(BaseModel):
    raw_input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def reported_tokens(self) -> int:
        return max(self.raw_input_tokens - self.cached_input_tokens, 0) + self.output_tokens


class HiddenEvaluationOutcome(BaseModel):
    assertions_passed: int = Field(ge=0)
    assertions_total: int = Field(ge=1)
    decision_checks_passed: int = Field(ge=0)
    decision_checks_total: int = Field(ge=0)
    regressions: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> HiddenEvaluationOutcome:
        if self.assertions_passed > self.assertions_total:
            raise ValueError("assertions_passed cannot exceed assertions_total")
        if self.decision_checks_passed > self.decision_checks_total:
            raise ValueError("decision_checks_passed cannot exceed decision_checks_total")
        return self

    @property
    def task_completion_rate(self) -> float:
        return self.assertions_passed / self.assertions_total

    @property
    def decision_adherence_rate(self) -> float | None:
        if not self.decision_checks_total:
            return None
        return self.decision_checks_passed / self.decision_checks_total

    @property
    def successful(self) -> bool:
        return (
            self.assertions_passed == self.assertions_total
            and self.decision_checks_passed == self.decision_checks_total
            and self.regressions == 0
        )


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


def _evaluation_program(command: str) -> Path:
    arguments = shlex.split(command)
    if not arguments:
        raise ValueError("evaluation command is empty")
    if Path(arguments[0]).name in {"python", "python3"}:
        if len(arguments) < 2:
            raise ValueError("Python evaluation command does not name a script")
        return Path(arguments[1]).expanduser().resolve()
    return Path(arguments[0]).expanduser().resolve()


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


def load_codex_trace_usage(path: Path) -> CodexTraceUsage:
    usage = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid Codex trace JSON at line {line_number}: {error}") from error
        if not isinstance(event, dict):
            raise TypeError(f"Invalid Codex trace event at line {line_number}: expected object")
        is_codex_completion = event.get("type") == "turn.completed"
        is_claude_result = event.get("type") == "result"
        if not (is_codex_completion or is_claude_result) or not isinstance(
            event.get("usage"), dict
        ):
            continue
        candidate = event["usage"]
        try:
            raw_input_tokens = candidate.get("input_tokens")
            cached_input_tokens = candidate.get(
                "cached_input_tokens", candidate.get("cache_read_input_tokens", 0)
            )
            output_tokens = candidate.get("output_tokens")
            if raw_input_tokens is None or output_tokens is None:
                raise KeyError("input_tokens/output_tokens")
            if is_claude_result:
                raw_input_tokens += cached_input_tokens
            usage = CodexTraceUsage(
                raw_input_tokens=raw_input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid agent usage at line {line_number}: {error}") from error
    if usage is None:
        raise ValueError("Agent trace contains no completed usage event")
    return usage


def load_hidden_evaluation_outcome(output: str) -> HiddenEvaluationOutcome:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Hidden evaluator produced no output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ValueError("Hidden evaluator's final line must be a JSON object") from error
    if not isinstance(payload, dict):
        raise TypeError("Hidden evaluator's final line must be a JSON object")
    return HiddenEvaluationOutcome.model_validate(payload)


def record_experiment_run(
    plan: ExperimentPlan,
    checkpoints: list[ExperimentCheckpoint],
    output: Path,
    *,
    run_id: str,
    worktree: Path,
    trace_path: Path,
    agent_b: str,
    model_b: str,
    duration_seconds: float,
    repeated_exploration: int,
    incorrect_assumptions: int,
    notes: str | None = None,
) -> ExperimentRun:
    if duration_seconds < 0 or repeated_exploration < 0 or incorrect_assumptions < 0:
        raise ValueError("Experiment duration and manual counts must be non-negative")
    assignments = {assignment.run_id: assignment for assignment in plan.assignments}
    if run_id not in assignments:
        raise ValueError(f"Unknown experiment run ID: {run_id}")
    assignment = assignments[run_id]
    destination = output.expanduser().resolve()
    existing = load_runs(destination) if destination.exists() else []
    if run_id in {item.run_id for item in existing}:
        raise ValueError(f"Experiment result already recorded for run: {run_id}")
    tasks = {task.id: task for task in plan.tasks}
    task = tasks[assignment.task_id]
    matching = [item for item in checkpoints if item.task_id == assignment.task_id]
    if len(matching) != 1:
        raise ValueError(f"Expected one Stage-A checkpoint for task: {assignment.task_id}")
    checkpoint = matching[0]
    validate_checkpoint(plan, checkpoint)

    repository = worktree.expanduser().resolve()
    resolved_head = _git_commit(repository, "HEAD")
    if resolved_head != checkpoint.commit:
        raise ValueError(
            f"Worktree HEAD does not match Stage-A checkpoint: {resolved_head or 'unresolved'}"
        )
    condition_path = repository / ".contextbridge" / "condition.md"
    if assignment.condition == ExperimentCondition.NO_CONTEXT:
        if condition_path.exists():
            raise ValueError("No-context run unexpectedly contains a condition input")
    else:
        source = {
            ExperimentCondition.RAW_HISTORY: checkpoint.transcript_path,
            ExperimentCondition.ONE_SHOT_SUMMARY: checkpoint.summary_path,
            ExperimentCondition.CONTEXTBRIDGE: checkpoint.context_pack_path,
        }[assignment.condition]
        if not condition_path.is_file():
            raise ValueError("Prepared run is missing .contextbridge/condition.md")
        if condition_path.read_bytes() != Path(source).expanduser().resolve().read_bytes():
            raise ValueError("Prepared condition input does not match the recorded checkpoint artifact")

    trace = trace_path.expanduser().resolve()
    usage = load_codex_trace_usage(trace)
    test_arguments = shlex.split(task.test_command)
    if not test_arguments:
        raise ValueError(f"Task has an empty test command: {assignment.task_id}")
    if test_arguments and test_arguments[0] in {"python", "python3"}:
        test_arguments[0] = sys.executable
    test = subprocess.run(
        test_arguments,
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    artifact_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-.") or "run"
    artifact_slug = f"{artifact_slug[:64]}-{sha256(run_id.encode()).hexdigest()[:8]}"
    artifacts = destination.parent / f"{destination.stem}.artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    test_output_path = artifacts / f"{artifact_slug}.test.txt"
    test_output = (
        f"$ {task.test_command}\n"
        f"exit_code={test.returncode}\n\n"
        f"--- stdout ---\n{test.stdout}\n"
        f"--- stderr ---\n{test.stderr}"
    )
    test_output_path.write_text(test_output, encoding="utf-8")
    hidden_outcome = None
    evaluation = None
    evaluation_output_path = None
    if task.evaluation_command:
        evaluator = _evaluation_program(task.evaluation_command)
        if not evaluator.is_file():
            raise ValueError("Hidden evaluator does not exist")
        if task.evaluation_sha256 is None:
            raise ValueError("Hidden evaluator is not pinned by SHA-256")
        if sha256(evaluator.read_bytes()).hexdigest() != task.evaluation_sha256:
            raise ValueError("Hidden evaluator SHA-256 does not match the manifest")
        evaluation_arguments = shlex.split(task.evaluation_command)
        if not evaluation_arguments:
            raise ValueError(f"Task has an empty evaluation command: {assignment.task_id}")
        if evaluation_arguments[0] in {"python", "python3"}:
            evaluation_arguments[0] = sys.executable
        evaluation = subprocess.run(
            evaluation_arguments,
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        hidden_outcome = load_hidden_evaluation_outcome(evaluation.stdout)
        evaluation_output_path = artifacts / f"{artifact_slug}.evaluation.txt"
        evaluation_output_path.write_text(
            f"$ [hidden evaluator]\n"
            f"exit_code={evaluation.returncode}\n\n"
            f"--- stdout ---\n{evaluation.stdout}\n"
            f"--- stderr ---\n{evaluation.stderr}",
            encoding="utf-8",
        )
    diff = subprocess.run(
        ["git", "-C", str(repository), "diff", "HEAD", "--binary", "--no-ext-diff"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        raise ValueError(f"Could not capture experiment diff: {diff.stderr.strip()}")
    status = subprocess.run(
        ["git", "-C", str(repository), "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError(f"Could not capture experiment status: {status.stderr.strip()}")
    diff_path = artifacts / f"{artifact_slug}.diff"
    diff_path.write_text(
        f"# git status --short\n{status.stdout}\n"
        f"# git diff HEAD --binary --no-ext-diff\n{diff.stdout}",
        encoding="utf-8",
    )
    run = ExperimentRun(
        run_id=run_id,
        agent_a=checkpoint.agent_a,
        agent_b=agent_b,
        model_a=checkpoint.model_a,
        model_b=model_b,
        tests_passed=(
            test.returncode == 0 and (hidden_outcome is None or hidden_outcome.successful)
        ),
        duration_seconds=duration_seconds,
        input_tokens=usage.reported_tokens,
        raw_input_tokens=usage.raw_input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        output_tokens=usage.output_tokens,
        trace_path=str(trace),
        trace_sha256=sha256(trace.read_bytes()).hexdigest(),
        test_exit_code=test.returncode,
        test_output_path=str(test_output_path),
        test_output_sha256=sha256(test_output_path.read_bytes()).hexdigest(),
        diff_path=str(diff_path),
        diff_sha256=sha256(diff_path.read_bytes()).hexdigest(),
        assertions_passed=(hidden_outcome.assertions_passed if hidden_outcome else None),
        assertions_total=(hidden_outcome.assertions_total if hidden_outcome else None),
        decision_checks_passed=(
            hidden_outcome.decision_checks_passed if hidden_outcome else None
        ),
        decision_checks_total=(
            hidden_outcome.decision_checks_total if hidden_outcome else None
        ),
        regressions=hidden_outcome.regressions if hidden_outcome else None,
        evaluation_exit_code=evaluation.returncode if evaluation else None,
        evaluation_output_path=(str(evaluation_output_path) if evaluation_output_path else None),
        evaluation_output_sha256=(
            sha256(evaluation_output_path.read_bytes()).hexdigest()
            if evaluation_output_path
            else None
        ),
        repeated_exploration=repeated_exploration,
        incorrect_assumptions=incorrect_assumptions,
        notes=notes,
    )

    score_experiment(plan, [*existing, run])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as stream:
        stream.write(run.model_dump_json() + "\n")
    return run


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
        if task.evaluation_command:
            try:
                evaluator = _evaluation_program(task.evaluation_command)
            except ValueError as error:
                errors.append(str(error))
            else:
                if not evaluator.is_file():
                    errors.append("hidden evaluator does not exist")
                elif task.evaluation_sha256 is None:
                    errors.append("hidden evaluator is not pinned by SHA-256")
                elif sha256(evaluator.read_bytes()).hexdigest() != task.evaluation_sha256:
                    errors.append("hidden evaluator SHA-256 does not match the manifest")
        elif task.evaluation_sha256 is not None:
            errors.append("hidden evaluator SHA-256 is set without an evaluation command")
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
                average_task_completion_rate=_average(
                    [
                        run.assertions_passed / run.assertions_total
                        for run in condition_runs
                        if run.assertions_passed is not None and run.assertions_total is not None
                    ]
                ),
                average_decision_adherence_rate=_average(
                    [
                        run.decision_checks_passed / run.decision_checks_total
                        for run in condition_runs
                        if run.decision_checks_passed is not None
                        and run.decision_checks_total is not None
                        and run.decision_checks_total > 0
                    ]
                ),
                average_regressions=_average(
                    [run.regressions for run in condition_runs if run.regressions is not None]
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
        "| Condition | Runs | Strict pass | Task outcome | Decision | Regressions | Seconds | Reported tokens | Re-exploration | Wrong assumptions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for score in report.scores:
        pass_rate = "—" if score.pass_rate is None else f"{score.pass_rate:.1%}"
        task_outcome = (
            score.average_task_completion_rate * 100
            if score.average_task_completion_rate is not None
            else None
        )
        decision_adherence = (
            score.average_decision_adherence_rate * 100
            if score.average_decision_adherence_rate is not None
            else None
        )
        output.append(
            f"| {score.condition.value} | {score.completed}/{score.planned} | {pass_rate} | "
            f"{value(task_outcome, '%')} | {value(decision_adherence, '%')} | "
            f"{value(score.average_regressions)} | {value(score.average_duration_seconds)} | "
            f"{value(score.average_input_tokens)} | "
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
