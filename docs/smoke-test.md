# Live cross-agent smoke test and preliminary comparison

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
one-shot summary. To check whether the experiment plumbing could expose meaningful differences, the
same Agent A checkpoint was subsequently replayed once under all four conditions.

## Matched four-condition replay

All four Agent B runs used fresh Codex processes with the same model, reasoning setting, fixture
commit, Stage A file content, and Stage B prompt. Only the supplied handoff context changed. The raw
condition received all 18 permitted Claude events; the summary condition received a fixed 205-token
summary of Agent A's outcome; and the ContextBridge condition received the validated 1,913-token
pack. Durations come from the first and last timestamps in each persisted Codex trace.

| Condition | Handoff tokens | Agent B reported tokens | Seconds | Tool calls | Target tests | Final diff +/− |
|---|---:|---:|---:|---:|---:|---:|
| no context | 0 | 31,702 | 67.9 | 8 | 2/2 | 18/5 |
| raw history | 2,926 | 31,414 | 66.4 | 6 | 2/2 | 11/3 |
| one-shot summary | 205 | 18,040 | 54.3 | 8 | 2/2 | 8/2 |
| ContextBridge | 1,913 | 10,586 | 133.4 | 5 | 2/2 | 8/2 |

In this replay, ContextBridge used 66.3% fewer Agent B tokens than raw history and 66.6% fewer than
no context. It also produced the same minimal tracked diff as the summary condition. Raw history and
no context both expanded the implementation beyond the specified remaining change; the no-context
run additionally searched the repository, attempted a missing interpreter, ran unrelated failing
tests, and authored its own edge-case probe. The ContextBridge run used the fewest tool calls and
went directly to the inherited TODO.

“Agent B reported tokens” is the Codex CLI total shown to the user: uncached input plus output. Full
trace input is higher because it includes cached harness prompts. The same definition is used for
all four rows.

ContextBridge was nevertheless the slowest run by wall-clock time. With one run per condition,
latency, model-service variance, and ordering effects dominate, so this result supports neither a
speed claim nor statistical superiority. The planned twelve-run study remains necessary. It should
also randomize condition order and repeat tasks before any numbers are promoted to the project
headline or a résumé.

## Second matched task: refresh-token replay

On 2026-09-14, the same protocol completed a second four-condition replay on the
`auth-refresh` fixture. Claude Code 2.1.236 routed to `deepseek-v4-flash` selected whole-family
revocation, implemented replay evidence, and deliberately stopped before setting the revocation
flag. Its checkpoint was `4d4abc7adaf69f88a336fe4836e8eaf382adf626`; one of two targeted tests
still failed as intended. The Stage A API call cost $0.463926.

Every Agent B run used `gpt-5.6-sol` with medium reasoning and the same prompt and checkpoint. The
condition order was one-shot summary, no context, raw history, then ContextBridge. The recorder
reran the pinned tests and derived reported tokens from each final Codex usage event.

| Condition | Agent B reported tokens | Seconds | Re-exploration | Target tests |
|---|---:|---:|---:|---:|
| no context | 28,853 | 74.8 | 7 | 2/2 |
| raw history | 29,880 | 71.5 | 6 | 2/2 |
| one-shot summary | 21,380 | 104.0 | 4 | 2/2 |
| ContextBridge | 29,443 | 59.5 | 5 | 2/2 |

This task produced a different trade-off from configuration precedence. ContextBridge was the
fastest condition and avoided two repeated exploration actions relative to no context, but it did
not reduce tokens relative to raw history. The one-shot summary used the fewest tokens yet was the
slowest. All conditions produced the required behavior, so this result argues for reporting several
metrics rather than reducing handoff quality to token count alone.

The first generated summary incorrectly promoted Agent A's temporary “stop before revocation”
instruction into an Agent B constraint. That draft was excluded, the fixed summary prompt was
clarified to distinguish stage-local stopping instructions from continuing constraints, and the
summary was regenerated before any Agent B run. This is both a protocol correction and a concrete
example of why handoff provenance and instruction precedence matter.

The committed [auth-refresh artifacts](../experiments/live/auth-refresh/) contain the four Codex
JSONL traces, condition inputs, result records, test output, final diffs, and SHA-256 hashes. The
sample is still one run per condition and remains descriptive rather than statistically significant.

## Third matched task: cache invalidation ordering

The final fixture task used Stage A checkpoint
`cd3eef8a47a71442f1205e54c6bc9aa5ebc87f1f`. Claude/DeepSeek moved cache invalidation behind the
successful store commit, documented that boundary, and deliberately left an incorrect invalidation
inside the `CommitError` path. The targeted suite remained 1/2. Stage A cost $0.393248.

| Condition | Agent B reported tokens | Seconds | Re-exploration | Target tests |
|---|---:|---:|---:|---:|
| no context | 39,511 | 95.6 | 7 | 2/2 |
| raw history | 14,630 | 67.6 | 5 | 2/2 |
| one-shot summary | 10,861 | 45.3 | 4 | 2/2 |
| ContextBridge | 23,221 | 1,708.1 | 4 | 2/2 |

ContextBridge reduced reported tokens by 41.2% relative to no context and tied the summary for the
fewest repeated exploration actions, but the summary was smaller and faster. The ContextBridge run
also encountered a model stream disconnect and retry. The completed result and full 1,708-second
wall time are retained; no selective rerun was substituted.

The committed [cache-race artifacts](../experiments/live/cache-race/) preserve the handoff inputs,
Codex traces, test evidence, diffs, and hashes. A
[three-task descriptive summary](../experiments/live/summary.md) combines all twelve runs. Across
those runs ContextBridge averaged 36.8% fewer reported tokens than no context and 16.7% fewer than
raw history, while the one-shot summary remained the lowest-token condition. With only one
observation per task and condition, this is a portfolio-scale experiment, not a statistical
benchmark.
