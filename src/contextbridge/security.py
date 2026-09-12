from __future__ import annotations

import re

SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(r"((?:password|passwd|api[_-]?key|token)\s*[=:]\s*)[^\s,;]+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
]


def redact_secrets(value: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value
