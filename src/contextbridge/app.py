from __future__ import annotations

from pathlib import Path

from .adapters.extractors import StructuredNotesExtractor
from .adapters.sources import ClaudeCodeSource, CodexSource, DshSource
from .adapters.targets import MarkdownTarget
from .database import ContextDatabase
from .plugins import ExtractorPlugin, PluginRegistry


def create_registry(extra_extractor: ExtractorPlugin | None = None) -> PluginRegistry:
    registry = (
        PluginRegistry()
        .register_source(ClaudeCodeSource())
        .register_source(CodexSource())
        .register_source(DshSource())
        .register_extractor(StructuredNotesExtractor())
        .register_target(MarkdownTarget())
    )
    if extra_extractor is not None:
        registry.register_extractor(extra_extractor)
    return registry


def open_database(cwd: Path) -> ContextDatabase:
    return ContextDatabase(cwd / ".contextbridge" / "contextbridge.db")
