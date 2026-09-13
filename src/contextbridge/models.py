from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    FACT = "fact"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    OPEN_LOOP = "open_loop"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    POSSIBLY_STALE = "possibly_stale"


class SourceRef(BaseModel):
    agent: str
    session_id: str
    message_id: str
    path: Path


class ContextEvent(BaseModel):
    id: str
    type: str = "message.observed"
    occurred_at: datetime = Field(default_factory=utc_now)
    source: SourceRef
    content: str


class MemoryDraft(BaseModel):
    type: MemoryType
    content: str
    reason: str | None = None
    related_files: list[str] = Field(default_factory=list)
    source: SourceRef


class Memory(MemoryDraft):
    id: str
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    source_commit: str | None = None


class SyncResult(BaseModel):
    events: list[ContextEvent]
    cursor: str


class ProjectState(BaseModel):
    root: Path
    branch: str | None = None
    commit: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    recent_commits: list[str] = Field(default_factory=list)


class ContextPack(BaseModel):
    task: str
    generated_at: datetime = Field(default_factory=utc_now)
    memories: list[Memory]
    excerpts: list[ContextEvent] = Field(default_factory=list)
    project_state: ProjectState | None = None
