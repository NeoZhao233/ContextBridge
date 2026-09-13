from __future__ import annotations

import re

from .models import ContextEvent, ContextPack, Memory, MemoryStatus, MemoryType, ProjectState

TYPE_WEIGHT = {
    MemoryType.OPEN_LOOP: 4,
    MemoryType.CONSTRAINT: 3,
    MemoryType.DECISION: 2,
    MemoryType.FACT: 1,
}


def estimate_tokens(text: str) -> int:
    """Conservative provider-neutral estimate for Latin and CJK text."""
    ascii_count = sum(character.isascii() for character in text)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def truncate_to_tokens(text: str, token_budget: int) -> str:
    if estimate_tokens(text) <= token_budget:
        return text
    suffix = "\n[… excerpt truncated]"
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle] + suffix) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + suffix


def build_context_pack(
    task: str,
    memories: list[Memory],
    limit: int = 20,
    token_budget: int = 4_000,
    project_state: ProjectState | None = None,
    excerpts: list[ContextEvent] | None = None,
    excerpt_limit: int = 6,
) -> ContextPack:
    terms = {term.lower() for term in re.split(r"[^\w./-]+", task) if len(term) > 1}

    def score(memory: Memory) -> tuple[int, str]:
        haystack = " ".join(
            [memory.content, memory.reason or "", *memory.related_files]
        ).lower()
        overlap = sum(term in haystack for term in terms)
        stale_penalty = int(memory.status == MemoryStatus.POSSIBLY_STALE)
        return overlap * 10 + TYPE_WEIGHT[memory.type] - stale_penalty, memory.created_at.isoformat()

    ranked = sorted(memories, key=score, reverse=True)
    selected: list[Memory] = []
    render_overhead = min(300, max(100, token_budget // 10))
    if project_state is not None:
        repository_text = " ".join(
            [
                str(project_state.root),
                project_state.branch or "",
                project_state.commit or "",
                *project_state.changed_files,
                *project_state.recent_commits,
            ]
        )
        render_overhead += estimate_tokens(repository_text)
    used = estimate_tokens(task) + render_overhead
    for memory in ranked:
        cost = estimate_tokens(
            " ".join([memory.content, memory.reason or "", *memory.related_files])
        ) + 20
        if selected and used + cost > token_budget:
            continue
        if used + cost > token_budget or len(selected) >= max(limit, 0):
            break
        selected.append(memory)
        used += cost

    selected_sources = {
        (memory.source.agent, memory.source.session_id, memory.source.message_id)
        for memory in selected
    }

    def excerpt_score(event: ContextEvent) -> tuple[int, str]:
        overlap = sum(term in event.content.lower() for term in terms)
        return overlap, event.occurred_at.isoformat()

    selected_excerpts: list[ContextEvent] = []
    for event in sorted(excerpts or [], key=excerpt_score, reverse=True):
        source_key = (event.source.agent, event.source.session_id, event.source.message_id)
        if source_key in selected_sources or len(selected_excerpts) >= max(excerpt_limit, 0):
            continue
        remaining = token_budget - used - 20
        if remaining <= 20:
            break
        content = truncate_to_tokens(event.content, min(remaining, 1_200))
        cost = estimate_tokens(content) + 20
        if used + cost > token_budget:
            continue
        selected_excerpts.append(event.model_copy(update={"content": content}))
        used += cost
    return ContextPack(
        task=task,
        memories=selected,
        excerpts=selected_excerpts,
        project_state=project_state,
    )
