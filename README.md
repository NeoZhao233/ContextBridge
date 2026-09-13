# ContextBridge

[![CI](https://github.com/NeoZhao233/ContextBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/NeoZhao233/ContextBridge/actions/workflows/ci.yml)

ContextBridge is a local-first context handoff harness for coding agents. It turns selected Claude
Code, Codex, and DeepSeek Harness (DSH) session messages into attributed project memories, then
builds a compact, task-specific Context Pack for the next agent.

The project borrows DeepSeek Harness's "everything is a plugin" principle while deliberately keeping the resume-project MVP small: sources, extractors, and targets are plugins; the core owns only stable contracts, storage, ranking, and provenance.

## Why ContextBridge?

Switching from Claude Code to Codex or another coding agent usually loses the decisions, constraints, and current work state built up in the previous conversation. Copying the full transcript is expensive and noisy; a one-shot summary loses provenance and quickly becomes stale.

ContextBridge keeps a local, inspectable project memory and generates only the context needed for the next task.

## MVP capabilities

- Incremental, idempotent JSONL ingestion for Claude Code, Codex, and DSH.
- Four memory types: facts, decisions, constraints, and open loops.
- SQLite-backed local event and memory storage.
- Every memory retains its source agent, session, message, and file.
- SQLite FTS5 retrieval and task-aware Context Pack ranking.
- Zero-configuration fallback to task-relevant, token-bounded conversation excerpts.
- Provider-neutral token-budget enforcement with Markdown output.
- File-level Git staleness warnings.
- Basic secret redaction and inspect-before-handoff workflow.
- Small `SourcePlugin`, `ExtractorPlugin`, and `TargetPlugin` contracts.
- Thin DSH tool plugin that loads Context Packs for the active DSH workspace.
- One-command capture with project-aware session discovery and a Git-aware handoff pack.
- Shared handoff/resume Agent Skills installable for both Claude Code and Codex.

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
contextbridge inspect --task "continue the DSH adapter" --token-budget 4000
contextbridge handoff --task "continue the DSH adapter" --output context.md --token-budget 4000
```

For the actual switch-agent workflow, `capture` combines session discovery, incremental import,
memory extraction, Git-state capture, retrieval, and handoff rendering:

```bash
contextbridge capture \
  --task "finish the authentication refactor and run its tests" \
  --output .contextbridge/handoff.md

contextbridge validate --path .contextbridge/handoff.md --token-budget 4000
```

Run it from the project root. ContextBridge searches for the newest Claude Code and Codex JSONL
sessions whose metadata references that project, so copying the transcript is unnecessary. DSH
requires an explicit persistence root because its host application deliberately controls that
location:

```bash
export CONTEXTBRIDGE_DSH_SESSION_ROOT=/absolute/path/to/dsh-session-root
```

ContextBridge imports DSH's current v3 format. DSH normally persists
`session.v3.jsonl.zstd`; install the optional reader once with `pip install -e '.[dsh]'`.
Uncompressed DSH JSONL works with the base installation. If automatic discovery cannot identify
any session, select one explicitly:

```bash
contextbridge capture \
  --source claude-code \
  --path /path/to/session.jsonl \
  --task "finish the authentication refactor" \
  --output .contextbridge/handoff.md
```

For example, an explicit DSH handoff capture is:

```bash
contextbridge capture \
  --source dsh \
  --path /path/to/session.v3.jsonl.zstd \
  --task "finish the authentication refactor" \
  --output .contextbridge/handoff.md
```

The receiving agent reads `.contextbridge/handoff.md`. The pack contains the task, branch and
commit, working-tree changes, recent commits, ranked memories, provenance, stale-memory warnings,
and a small set of task-relevant conversation excerpts. The excerpts make ordinary conversations
usable without another API call and are clearly marked as untrusted historical data. Use
`--extractor llm` with the provider variables above when you also want durable structured memories;
the offline extractor derives structured memories only from explicit `FACT:`, `DECISION:`,
`CONSTRAINT:`, and `TODO:` notes.

`capture`, `inspect`, and `handoff` validate their rendered output before returning it. The standalone
`validate` command is useful in scripts and receiving-agent skills; it checks the required task and
repository sections, source attribution, excerpt safety marker, common secret patterns, and the
estimated token budget. It exits nonzero for an invalid pack.

### Agent commands

Install the bundled skills into the current repository:

```bash
contextbridge install-skills --agent all --scope project
```

This creates the same two skills under `.agents/skills` for Codex and `.claude/skills` for Claude
Code. Use `--scope user` to make them available in every project, or `--force` to update an existing
installation.

In the agent interfaces:

```text
Codex:       $contextbridge-handoff / $contextbridge-resume
Claude Code: /contextbridge-handoff /contextbridge-resume
```

The handoff skill derives the continuation task, invokes `capture`, and reviews the generated pack.
The resume skill treats the pack as historical context, verifies it against the working tree, and
continues the requested task. Both are thin orchestration layers: storage and retrieval remain in
the Python core.

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

Fixtures cover common Claude Code `user`/`assistant` records, Codex `response_item` messages, and
DSH `user/message` and `assistant/message` events. Tool results, developer instructions,
replacement summaries, streaming chunks, image payloads, and private reasoning records are
intentionally excluded from handoff content.

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

The first third-party integration is the [DSH adapter](integrations/dsh-plugin/README.md). Its thin
JavaScript target lets a running DSH agent request Context Packs, while the Python DSH source reads
the same append-only session format used by the host. Storage and ranking remain agent-independent.

## Resume-project evaluation

Run the deterministic offline benchmark:

```bash
contextbridge evaluate
```

It compares no context, verbose synthetic history, a controlled one-shot-summary baseline,
structured ContextBridge memory, and the zero-API offline-excerpt fallback across ten cases. It
reports required-memory recall, precision, source coverage, and estimated input tokens. This is a
retrieval regression suite, not a coding-task success claim.

The second evaluation layer starts with three real two-stage coding tasks under all four conditions,
for twelve runs measuring test pass rate, input tokens, time, and repeated exploration. Five tasks
and twenty runs are the stretch target. See [the evaluation protocol](docs/evaluation.md) for metric
definitions, current offline results, limitations, and the end-to-end design.

The repository also includes executable experiment bookkeeping:

```bash
contextbridge experiment-plan \
  --manifest experiments/tasks.example.json \
  --output experiments/plan.json

contextbridge experiment-report \
  --plan experiments/plan.json \
  --results experiments/results.jsonl
```

Plans assign every task to all four conditions in seeded random order. Reports reject duplicate or
unknown run IDs and leave incomplete runs visible rather than silently dropping them.

## Non-goals

The MVP does not provide cloud sync, multi-user collaboration, a plugin marketplace, a vector database, semantic conflict resolution, or a web dashboard.

## Status

Early MVP. Claude Code does not publish a stable transcript schema, and Codex and DSH records may
evolve, so adapters parse defensively and test explicit fixtures rather than claiming universal
compatibility.

## License

MIT
