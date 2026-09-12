# Architecture

ContextBridge is a context harness, not another agent runtime. It takes architectural inspiration from DeepSeek Harness: keep the kernel small, expose capabilities through plugins, and make every derived result traceable to an event.

## Core responsibilities

The core owns only:

- versioned Pydantic data contracts;
- append-only normalized events and SQLite projections;
- plugin registration;
- SQLite FTS5 retrieval, task-aware ranking, and token-budget selection;
- provenance and stale-state representation.

Agent-specific session formats and output formats belong to plugins.

```text
Session JSONL
    │
    ▼
Source plugin ──► immutable events ──► Extractor plugin ──► attributed memories
                                                               │
Task ───────────────────────────────► ranking ──────────────────┤
                                                               ▼
                                                        Target plugin
                                                               │
                                                               ▼
                                                         Context Pack
```

## Plugin seams

- `SourcePlugin.sync()` incrementally converts an agent session into normalized events.
- `ExtractorPlugin.extract()` derives structured memories from those events.
- `TargetPlugin.render()` renders selected memories for a destination agent.

The MVP uses Python `Protocol` definitions instead of building a general dependency-injection
framework. DSH integration remains a thin JavaScript plugin that invokes the Python CLI.

The initial DSH target adapter is implemented as a small JavaScript plugin. It registers a typed
`contextbridge_handoff` tool through DSH's public `tools` service, derives the project root from the
calling session, and delegates retrieval to the Python CLI. It does not duplicate storage or
retrieval logic.

## Storage model

SQLite contains three durable tables plus an FTS projection:

- `events`: immutable observations with source attribution;
- `memories`: rebuildable facts, decisions, constraints, and open loops;
- `sync_cursors`: per-source incremental import positions.

An FTS5 projection indexes memory content, rationale, and related files. Context Pack construction
uses FTS candidates, type/recency relevance, and a conservative Latin/CJK token estimate to remain
inside a caller-provided budget without binding the core to one tokenizer or model vendor.

Memory IDs are content-addressed, making repeated imports idempotent. Each memory records the source agent, session, message, file, and Git commit when available.

## Deliberate MVP boundaries

- Manual synchronization rather than a daemon.
- SQLite rather than remote or vector storage.
- Three focused plugin seams rather than a Cordis reimplementation.
- File-level Git staleness warnings rather than semantic invalidation.
- Structured-note extraction for deterministic offline demos.
- An OpenAI-compatible LLM extractor for natural-language conversations, with source validation,
  path validation, and pre-request secret redaction.
