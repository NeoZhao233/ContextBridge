from __future__ import annotations

import re

from .models import ContextPack, Memory, MemoryStatus, MemoryType


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


def build_context_pack(
    task: str,
    memories: list[Memory],
    limit: int = 20,
    token_budget: int = 4_000,
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
    used = estimate_tokens(task) + 80
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
    return ContextPack(task=task, memories=selected)
