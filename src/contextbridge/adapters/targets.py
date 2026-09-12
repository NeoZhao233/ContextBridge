from __future__ import annotations

from ..models import ContextPack, MemoryStatus, MemoryType
from ..security import redact_secrets

HEADINGS = [
    (MemoryType.DECISION, "Relevant decisions"),
    (MemoryType.CONSTRAINT, "Constraints"),
    (MemoryType.FACT, "Project facts"),
    (MemoryType.OPEN_LOOP, "Open loops"),
]


class MarkdownTarget:
    name = "markdown"

    def render(self, pack: ContextPack) -> str:
        output = [
            "# Context Pack",
            "",
            "## Handoff instructions",
            "",
            (
                "Continue the current task from this project state. Inspect the working tree before "
                "editing, verify possibly stale memories against the repository, and preserve existing "
                "user changes."
            ),
            "",
            "## Current task",
            "",
            pack.task,
            "",
        ]
        if pack.project_state is not None:
            state = pack.project_state
            output.extend(["## Repository state", "", f"- Root: `{state.root}`"])
            if state.branch:
                output.append(f"- Branch: `{state.branch}`")
            if state.commit:
                output.append(f"- Commit: `{state.commit}`")
            output.extend(["", "### Working tree", ""])
            output.extend(f"- `{line}`" for line in state.changed_files)
            if not state.changed_files:
                output.append("- Clean")
            if state.recent_commits:
                output.extend(["", "### Recent commits", ""])
                output.extend(f"- `{line}`" for line in state.recent_commits)
            output.append("")
        for memory_type, heading in HEADINGS:
            memories = [memory for memory in pack.memories if memory.type == memory_type]
            if not memories:
                continue
            output.extend([f"## {heading}", ""])
            for memory in memories:
                stale = "⚠ Possibly stale — " if memory.status == MemoryStatus.POSSIBLY_STALE else ""
                output.append(f"- {stale}{memory.content}")
                output.append(
                    f"  Source: {memory.source.agent} / {memory.source.session_id} / "
                    f"message {memory.source.message_id}"
                )
                if memory.related_files:
                    output.append(f"  Files: {', '.join(memory.related_files)}")
            output.append("")
        output.extend([f"Generated: {pack.generated_at.isoformat()}", ""])
        return redact_secrets("\n".join(output))
