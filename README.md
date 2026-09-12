# ContextBridge

ContextBridge is a local-first context handoff harness for coding agents. It turns selected Claude Code and Codex session messages into attributed project memories, then builds a compact, task-specific Context Pack for the next agent.

The project borrows DeepSeek Harness's "everything is a plugin" principle while deliberately keeping the resume-project MVP small: sources, extractors, and targets are plugins; the core owns only stable contracts, storage, ranking, and provenance.

## Why ContextBridge?

Switching from Claude Code to Codex or another coding agent usually loses the decisions, constraints, and current work state built up in the previous conversation. Copying the full transcript is expensive and noisy; a one-shot summary loses provenance and quickly becomes stale.

ContextBridge keeps a local, inspectable project memory and generates only the context needed for the next task.

## MVP capabilities

- Incremental, idempotent JSONL ingestion for Claude Code and Codex.
- Four memory types: facts, decisions, constraints, and open loops.
- SQLite-backed local event and memory storage.
- Every memory retains its source agent, session, message, and file.
- Task-aware Context Pack ranking with Markdown output.
- File-level Git staleness warnings.
- Basic secret redaction and inspect-before-handoff workflow.
- Small `SourcePlugin`, `ExtractorPlugin`, and `TargetPlugin` contracts.

The deterministic MVP extractor recognizes explicit notes in session text:

```text
FACT: Authentication lives in src/auth/service.py
DECISION: Use SQLite because the MVP is single-user
CONSTRAINT: Do not add a cloud dependency
TODO: Add concurrent login tests
```

For ordinary natural-language conversations, use the provider-neutral LLM extractor. It calls an
OpenAI-compatible chat-completions endpoint without depending on a provider SDK:

```bash
export CONTEXTBRIDGE_API_KEY="..."
export CONTEXTBRIDGE_MODEL="your-model"
export CONTEXTBRIDGE_BASE_URL="https://your-provider.example/v1"

contextbridge sync \
  --source claude-code \
  --path /path/to/session.jsonl \
  --extractor llm
```

The API key is read only from the environment, never accepted as a CLI argument. Common secret
patterns are redacted before conversation text is sent to the extraction provider. The structured
notes extractor remains the deterministic, offline default.

## Requirements

- Python 3.11+

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

contextbridge init
contextbridge sync --source claude-code --path examples/claude-session.jsonl
contextbridge status
contextbridge inspect --task "continue the DSH adapter"
contextbridge handoff --task "continue the DSH adapter" --output context.md
```

Without installing the package:

```bash
PYTHONPATH=src python -m contextbridge.cli init
PYTHONPATH=src python -m contextbridge.cli sync \
  --source claude-code --path examples/claude-session.jsonl
PYTHONPATH=src python -m contextbridge.cli inspect \
  --task "continue the DSH adapter"
```

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Fixtures cover common Claude Code `user`/`assistant` records and Codex `response_item` messages.
Tool results, image payloads, and private reasoning records are intentionally excluded from memory
extraction.

## Architecture

```text
Agent session
     │
     ▼
SourcePlugin ──► append-only events ──► ExtractorPlugin
                                               │
                                               ▼
                                      attributed memories
                                               │
Task ───────────────────────────────► rank and select
                                               │
                                               ▼
                                         TargetPlugin
                                               │
                                               ▼
                                          Context Pack
```

Adding a third agent should require a new source or target plugin without changing storage or ranking. See [the architecture notes](docs/architecture.md).

## Resume-project evaluation

The planned evaluation is intentionally compact:

1. Ten two-stage coding tasks comparing no context, raw history, one-shot summary, and ContextBridge.
2. Report completion rate, input tokens, and repeated exploration count.
3. Add a DSH adapter and report adapter LOC, implementation time, and core-code changes.

## Non-goals

The MVP does not provide cloud sync, multi-user collaboration, a plugin marketplace, a vector database, semantic conflict resolution, or a web dashboard.

## Status

Early MVP. Claude Code does not publish a stable transcript schema, and Codex rollout records may
evolve, so adapters parse defensively and test explicit fixtures rather than claiming universal
compatibility.

## License

MIT
