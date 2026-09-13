from __future__ import annotations

import json
import random
from datetime import datetime
from enum import StrEnum
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
