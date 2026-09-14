# Auth-refresh matched replay

This directory preserves the evidence for the 2026-09-14 four-condition replay described in
[`docs/smoke-test.md`](../../../docs/smoke-test.md). It is an observational sample, not a claim of
statistical significance.

- `handoffs/` contains the exact raw-history, fixed one-shot-summary, and ContextBridge inputs.
- `traces/` contains the four `codex exec --json` event streams.
- `evidence/` contains the recorder's targeted-test output and final Git diff for every run.
- `results.jsonl` contains machine-readable metrics and SHA-256 hashes for those files.
- `report.md` is the report rendered from `results.jsonl`.

All Agent B runs used Codex CLI 0.153.4, `gpt-5.6-sol`, medium reasoning, and the same Stage B
prompt. All started from Stage A checkpoint
`4d4abc7adaf69f88a336fe4836e8eaf382adf626`, produced by Claude Code 2.1.236 routed to
`deepseek-v4-flash`. Conditions ran in this seeded order: one-shot summary, no context, raw history,
ContextBridge.

`input_tokens` in the results uses the documented “reported tokens” definition:
`raw_input_tokens - cached_input_tokens + output_tokens`. `repeated_exploration` was manually
audited from command events using the protocol definition; `incorrect_assumptions` was zero in all
four traces.
