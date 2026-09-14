# Cache-race matched replay

This directory preserves the evidence for the 2026-09-14 four-condition `cache-race` replay
described in [`docs/smoke-test.md`](../../../docs/smoke-test.md). It is one observational sample per
condition, not a statistical superiority claim.

- `handoffs/` contains the exact raw-history, fixed one-shot-summary, and ContextBridge inputs.
- `traces/` contains the four `codex exec --json` event streams.
- `evidence/` contains the recorder's targeted-test output and final Git diff for every run.
- `results.jsonl` contains machine-readable metrics and SHA-256 hashes for those files.
- `report.md` is rendered directly from `results.jsonl`.

All Agent B runs used Codex CLI 0.153.4, `gpt-5.6-sol`, medium reasoning, and an identical Stage B
prompt. They started from Stage A checkpoint
`cd3eef8a47a71442f1205e54c6bc9aa5ebc87f1f`, produced by Claude Code 2.1.236 routed to
`deepseek-v4-flash`. The seeded order was raw history, ContextBridge, one-shot summary, no context.

The ContextBridge run experienced a model stream disconnect and retry and took 1,708.07 seconds.
The successful result is retained without a selective rerun. `input_tokens` means uncached input
plus output. Manual command-event review supplied `repeated_exploration`; all four traces had zero
incorrect assumptions.
