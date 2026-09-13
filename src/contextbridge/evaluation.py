from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field

from .adapters.targets import MarkdownTarget
from .context_pack import build_context_pack, estimate_tokens
from .models import ContextEvent, Memory, MemoryType, SourceRef


class EvaluationItem(BaseModel):
    id: str
    type: MemoryType
    content: str
    relevant: bool
    related_files: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    id: str
    task: str
    items: list[EvaluationItem]
    summary_ids: list[str]
    token_budget: int = 500


class StrategyResult(BaseModel):
    strategy: str
    recall: float
    precision: float
    source_coverage: float
    tokens: int


class EvaluationReport(BaseModel):
    dataset: str
    cases: int
    results: list[StrategyResult]


def load_cases(path: Path | None = None) -> list[EvaluationCase]:
    if path is None:
        raw = (
            resources.files("contextbridge")
            .joinpath("benchmarks/resume_retrieval.json")
            .read_text(encoding="utf-8")
        )
    else:
        raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    return [EvaluationCase.model_validate(case) for case in payload["cases"]]


def _score(
    strategy: str,
    selected_ids: set[str],
    relevant_ids: set[str],
    rendered: str,
    *,
    has_sources: bool,
) -> StrategyResult:
    relevant_selected = selected_ids & relevant_ids
    recall = len(relevant_selected) / len(relevant_ids) if relevant_ids else 1.0
    precision = len(relevant_selected) / len(selected_ids) if selected_ids else 0.0
    return StrategyResult(
        strategy=strategy,
        recall=recall,
        precision=precision,
        source_coverage=recall if has_sources else 0.0,
        tokens=estimate_tokens(rendered) if rendered else 0,
    )


def _render_synthetic_history(items: list[EvaluationItem]) -> str:
    messages = []
    for index, item in enumerate(items, start=1):
        messages.append(
            f"User message {index}: Investigate this part of the project and compare the available "
            "implementation options before making changes."
        )
        messages.append(
            "Assistant response: I inspected the relevant code, followed intermediate call paths, "
            "and ran diagnostic commands. The durable outcome from that exploration was: "
            f"{item.content} The conversation also contained temporary hypotheses, command output, "
            "and repeated navigation that is not needed by the receiving agent."
        )
    return "\n\n".join(messages)


def _synthetic_events(case: EvaluationCase) -> list[ContextEvent]:
    events: list[ContextEvent] = []
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    for index, item in enumerate(case.items, start=1):
        user_id = f"prompt-{item.id}"
        events.append(
            ContextEvent(
                id=user_id,
                type="message.user",
                occurred_at=base_time + timedelta(seconds=index * 2 - 1),
                source=SourceRef(
                    agent="fixture-agent",
                    session_id=case.id,
                    message_id=str(index * 2 - 1),
                    path=Path(f"{case.id}.jsonl"),
                ),
                content=(
                    "Investigate this part of the project and compare the available "
                    "implementation options before making changes."
                ),
            )
        )
        events.append(
            ContextEvent(
                id=item.id,
                type="message.assistant",
                occurred_at=base_time + timedelta(seconds=index * 2),
                source=SourceRef(
                    agent="fixture-agent",
                    session_id=case.id,
                    message_id=str(index * 2),
                    path=Path(f"{case.id}.jsonl"),
                ),
                content=(
                    "I inspected the relevant code, followed intermediate call paths, and ran "
                    "diagnostic commands. The durable outcome from that exploration was: "
                    f"{item.content} The conversation also contained temporary hypotheses, "
                    "command output, and repeated navigation that is not needed by the receiving "
                    "agent."
                ),
            )
        )
    return events


def evaluate_cases(cases: list[EvaluationCase]) -> EvaluationReport:
    totals: dict[str, list[StrategyResult]] = defaultdict(list)
    for case in cases:
        by_id = {item.id: item for item in case.items}
        relevant_ids = {item.id for item in case.items if item.relevant}
        source = SourceRef(
            agent="fixture-agent",
            session_id=case.id,
            message_id="1",
            path=Path(f"{case.id}.jsonl"),
        )
        memories = [
            Memory(
                id=item.id,
                type=item.type,
                content=item.content,
                related_files=item.related_files,
                source=source,
            )
            for item in case.items
        ]
        pack = build_context_pack(
            case.task,
            memories,
            limit=len(relevant_ids),
            token_budget=case.token_budget,
        )
        fallback_pack = build_context_pack(
            case.task,
            [],
            token_budget=case.token_budget,
            excerpts=_synthetic_events(case),
        )
        bridge_ids = {memory.id for memory in pack.memories}
        fallback_ids = {event.id for event in fallback_pack.excerpts}
        summary_items = [by_id[item_id] for item_id in case.summary_ids]
        contexts = {
            "no_context": (set(), "", False),
            "raw_history": (
                {item.id for item in case.items},
                _render_synthetic_history(case.items),
                True,
            ),
            "one_shot_summary": (
                {item.id for item in summary_items},
                "\n".join(item.content for item in summary_items),
                False,
            ),
            "contextbridge": (bridge_ids, MarkdownTarget().render(pack), True),
            "offline_excerpts": (
                fallback_ids,
                MarkdownTarget().render(fallback_pack),
                True,
            ),
        }
        for strategy, (selected_ids, rendered, has_sources) in contexts.items():
            totals[strategy].append(
                _score(
                    strategy,
                    selected_ids,
                    relevant_ids,
                    rendered,
                    has_sources=has_sources,
                )
            )

    results = []
    for strategy in (
        "no_context",
        "raw_history",
        "one_shot_summary",
        "contextbridge",
        "offline_excerpts",
    ):
        rows = totals[strategy]
        count = len(rows) or 1
        results.append(
            StrategyResult(
                strategy=strategy,
                recall=round(sum(row.recall for row in rows) / count, 6),
                precision=round(sum(row.precision for row in rows) / count, 6),
                source_coverage=round(sum(row.source_coverage for row in rows) / count, 6),
                tokens=sum(row.tokens for row in rows),
            )
        )
    return EvaluationReport(dataset="resume_retrieval_v2", cases=len(cases), results=results)


def render_report(report: EvaluationReport) -> str:
    output = [
        "# ContextBridge retrieval evaluation",
        "",
        f"Dataset: `{report.dataset}` ({report.cases} synthetic cases)",
        "",
        "| Strategy | Required recall | Precision | Source coverage | Total tokens |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in report.results:
        output.append(
            f"| {result.strategy} | {result.recall:.1%} | {result.precision:.1%} | "
            f"{result.source_coverage:.1%} | {result.tokens} |"
        )
    output.extend(
        [
            "",
            "This controlled benchmark measures retrieval behavior, not coding-task completion.",
            "",
        ]
    )
    return "\n".join(output)
