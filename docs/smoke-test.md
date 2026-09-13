# Live cross-agent smoke test

On 2026-09-13, ContextBridge completed one real Claude Code to Codex handoff using the bundled
configuration-precedence fixture. This is an integration smoke test, not a controlled comparison or
evidence of an improvement rate.

## Setup

- ContextBridge commit: `d7c4408`
- Fixture commit: `29e003c774cea9436eb1a5e7df397d77a1dafc4c`
- Agent A: Claude Code 2.1.236 routed to `deepseek-v4-flash`
- Agent B: a fresh Codex CLI session using `gpt-5.6-sol`, medium reasoning
- Condition: `contextbridge`

The baseline implementation loaded file values but ignored environment and CLI values. Its targeted
suite passed one of two tests.

## Handoff

Agent A inspected the implementation, selected `CLI > environment > file` precedence, implemented
the environment layer, and intentionally stopped before the CLI layer. The targeted suite still
passed one of two tests, with the remaining assertion isolated to the CLI override.

`contextbridge capture` discovered the persisted Claude session without a manually copied
transcript. It imported 18 events, extracted three memories, and produced a validated 1,913-token
Context Pack containing:

- the pinned repository commit and working-tree state;
- Agent A's exact diff and remaining failing assertion;
- the precedence decision with source attribution;
- the unfinished CLI merge as an explicit open loop.

A new Codex process received only the repository and Context Pack. It verified the inherited diff,
added the CLI layer without reverting Agent A's work, and passed both targeted tests. Its trace read
the handoff, relevant implementation, and targeted test; it did not inspect the original Claude
session or unrelated project files.

## Observations

The handoff succeeded end to end and demonstrates the intended emergency-resume workflow. Agent A's
run cost $0.304686 and reported 27,703 uncached input tokens, 203,392 cache-read input tokens, and
2,579 output tokens. Agent B reported 10,586 tokens. These provider-reported totals include each
agent harness's own prompts and tool loop, so they are not directly comparable to the 1,913-token
Context Pack estimate.

This single successful run does not show that ContextBridge beats no context, raw history, or a
one-shot summary. The planned twelve-run study is still required before making comparative claims.
