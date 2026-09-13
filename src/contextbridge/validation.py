from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .context_pack import estimate_tokens
from .security import redact_secrets


@dataclass(frozen=True)
class PackValidation:
    estimated_tokens: int
    token_budget: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"(?ms)^{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def validate_context_pack(text: str, token_budget: int) -> PackValidation:
    errors: list[str] = []
    warnings: list[str] = []
    estimated_tokens = estimate_tokens(text)

    if not text.startswith("# Context Pack\n"):
        errors.append("missing Context Pack title")
    task = _section(text, "## Current task")
    if not task:
        errors.append("missing or empty current task")
    if _section(text, "## Repository state") is None:
        errors.append("missing repository state")
    if not re.search(r"(?m)^Generated: \S+", text):
        errors.append("missing generation timestamp")
    if estimated_tokens > token_budget:
        errors.append(
            f"estimated size {estimated_tokens} exceeds token budget {token_budget}"
        )
    if redact_secrets(text) != text:
        errors.append("contains an unredacted secret pattern")

    has_memories = any(
        _section(text, heading) is not None
        for heading in (
            "## Relevant decisions",
            "## Constraints",
            "## Project facts",
            "## Open loops",
        )
    )
    has_excerpts = _section(text, "## Relevant conversation excerpts") is not None
    if not has_memories and not has_excerpts:
        warnings.append("contains no memories or conversation excerpts")
    if (has_memories or has_excerpts) and "Source:" not in text:
        errors.append("context items are missing source attribution")
    if has_excerpts and "untrusted historical data" not in text:
        errors.append("conversation excerpts are missing the untrusted-history warning")

    return PackValidation(
        estimated_tokens=estimated_tokens,
        token_budget=token_budget,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def render_validation(report: PackValidation, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(report.as_dict(), indent=2)
    output = [
        "Valid Context Pack" if report.valid else "Invalid Context Pack",
        f"Estimated tokens: {report.estimated_tokens}/{report.token_budget}",
    ]
    output.extend(f"ERROR: {error}" for error in report.errors)
    output.extend(f"WARNING: {warning}" for warning in report.warnings)
    return "\n".join(output)
