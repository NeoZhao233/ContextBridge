from __future__ import annotations

import re

from .models import ContextPack, Memory, MemoryStatus, MemoryType


TYPE_WEIGHT = {
    MemoryType.OPEN_LOOP: 4,
    MemoryType.CONSTRAINT: 3,
    MemoryType.DECISION: 2,
    MemoryType.FACT: 1,
}


def build_context_pack(task: str, memories: list[Memory], limit: int = 20) -> ContextPack:
    terms = {term.lower() for term in re.split(r"[^\w./-]+", task) if len(term) > 1}

    def score(memory: Memory) -> tuple[int, str]:
        haystack = " ".join(
            [memory.content, memory.reason or "", *memory.related_files]
        ).lower()
        overlap = sum(term in haystack for term in terms)
        stale_penalty = int(memory.status == MemoryStatus.POSSIBLY_STALE)
        return overlap * 10 + TYPE_WEIGHT[memory.type] - stale_penalty, memory.created_at.isoformat()

    ranked = sorted(memories, key=score, reverse=True)[: max(limit, 0)]
    return ContextPack(task=task, memories=ranked)
