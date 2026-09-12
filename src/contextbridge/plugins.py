from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import ContextEvent, ContextPack, MemoryDraft, SyncResult


class SourcePlugin(Protocol):
    name: str

    def sync(self, path: Path, cursor: str | None = None) -> SyncResult: ...


class ExtractorPlugin(Protocol):
    name: str

    def extract(self, events: list[ContextEvent]) -> list[MemoryDraft]: ...


class TargetPlugin(Protocol):
    name: str

    def render(self, pack: ContextPack) -> str: ...


class PluginRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourcePlugin] = {}
        self._extractors: dict[str, ExtractorPlugin] = {}
        self._targets: dict[str, TargetPlugin] = {}

    def register_source(self, plugin: SourcePlugin) -> PluginRegistry:
        self._sources[plugin.name] = plugin
        return self

    def register_extractor(self, plugin: ExtractorPlugin) -> PluginRegistry:
        self._extractors[plugin.name] = plugin
        return self

    def register_target(self, plugin: TargetPlugin) -> PluginRegistry:
        self._targets[plugin.name] = plugin
        return self

    def source(self, name: str) -> SourcePlugin:
        try:
            return self._sources[name]
        except KeyError as error:
            raise ValueError(f"Unknown source plugin: {name}") from error

    def extractor(self, name: str) -> ExtractorPlugin:
        try:
            return self._extractors[name]
        except KeyError as error:
            raise ValueError(f"Unknown extractor plugin: {name}") from error

    def target(self, name: str) -> TargetPlugin:
        try:
            return self._targets[name]
        except KeyError as error:
            raise ValueError(f"Unknown target plugin: {name}") from error

    def describe(self) -> dict[str, list[str]]:
        return {
            "sources": list(self._sources),
            "extractors": list(self._extractors),
            "targets": list(self._targets),
        }
