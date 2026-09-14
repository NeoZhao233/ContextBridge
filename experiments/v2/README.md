# V2 graded outcome pilot

This directory records the first seven completed runs of the hidden-evaluator pilot described in
[`docs/evaluation.md`](../../docs/evaluation.md). The pilot stopped when the Codex account reached
its usage limit during run 8; the incomplete run is intentionally not included in the result set.

The completed runs all used `gpt-5.6-sol` for Agent B and a Claude Code → DeepSeek Stage-A
checkpoint. The result is a partial, descriptive snapshot—not a finished 12-run comparison and not
a license to claim statistical superiority. The remaining five run IDs are listed in the report and
can be resumed with the same plan after the usage window recovers.

The report keeps strict pass separate from graded behavior, decision adherence, regressions, input
tokens, and exploration. This is the evidence layer that the original visible-test-only study was
missing.

See [partial-report.md](partial-report.md).
