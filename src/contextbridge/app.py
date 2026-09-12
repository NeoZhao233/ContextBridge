from __future__ import annotations

from pathlib import Path

from .adapters.extractors import StructuredNotesExtractor
from .adapters.sources import ClaudeCodeSource, CodexSource
from .adapters.targets import MarkdownTarget
from .database import ContextDatabase
from .plugins import PluginRegistry


def create_registry() -> PluginRegistry:
    return (
        PluginRegistry()
        .register_source(ClaudeCodeSource())
        .register_source(CodexSource())
        .register_extractor(StructuredNotesExtractor())
        .register_target(MarkdownTarget())
    )


def open_database(cwd: Path) -> ContextDatabase:
    return ContextDatabase(cwd / ".contextbridge" / "contextbridge.db")
