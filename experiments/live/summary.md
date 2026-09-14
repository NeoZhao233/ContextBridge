# Preliminary matched-task summary

Three two-stage fixture tasks were each resumed once under no context, raw history, a fixed one-shot
summary, and ContextBridge: twelve Agent B runs total. Every run started from its task's single
shared Stage A checkpoint and used Codex `gpt-5.6-sol` with medium reasoning. All 12 targeted runs
passed.

| Condition | Runs | Test pass | Mean reported tokens | Mean seconds |
|---|---:|---:|---:|---:|
| no context | 3 | 100% | 33,355 | 79.4 |
| raw history | 3 | 100% | 25,308 | 68.5 |
| one-shot summary | 3 | 100% | 16,760 | 67.9 |
| ContextBridge | 3 | 100% | 21,083 | 633.6 |

Across these three matched tasks, ContextBridge used 36.8% fewer reported Agent B tokens than no
context and 16.7% fewer than raw history. The fixed one-shot summary used 25.8% fewer tokens than
ContextBridge, so the evidence does not support a “best overall” claim. ContextBridge's mean latency
is dominated by a retained 1,708-second model stream failure in `cache-race`; excluding it would be
a post-hoc change and is not used in the table.

These are descriptive means over one run per task and condition. They demonstrate a working,
auditable cross-agent experiment and expose trade-offs, but do not estimate statistical
significance. The configuration-precedence run predates the evidence recorder; the later
[`auth-refresh`](auth-refresh/) and [`cache-race`](cache-race/) directories include JSONL traces,
test output, diffs, and recorded SHA-256 hashes.
