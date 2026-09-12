from __future__ import annotations

import re

from ..models import ContextEvent, MemoryDraft, MemoryType

LABELS = {
    "FACT": MemoryType.FACT,
    "DECISION": MemoryType.DECISION,
    "CONSTRAINT": MemoryType.CONSTRAINT,
    "TODO": MemoryType.OPEN_LOOP,
    "OPEN LOOP": MemoryType.OPEN_LOOP,
}
NOTE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(FACT|DECISION|CONSTRAINT|TODO|OPEN LOOP)\s*:\s*(.+)$",
    re.IGNORECASE,
)
FILE_PATTERN = re.compile(r"(?:^|[\s`'(])([\w@.-]+(?:/[\w@.-]+)+\.[A-Za-z0-9]+)(?=$|[\s`'),:])")


class StructuredNotesExtractor:
    name = "structured-notes"

    def extract(self, events: list[ContextEvent]) -> list[MemoryDraft]:
        memories: list[MemoryDraft] = []
        for event in events:
            for line in event.content.splitlines():
                if not (match := NOTE_PATTERN.match(line)):
                    continue
                content = match.group(2).strip()
                memories.append(
                    MemoryDraft(
                        type=LABELS[match.group(1).upper()],
                        content=content,
                        related_files=FILE_PATTERN.findall(content),
                        source=event.source,
                    )
                )
        return memories
