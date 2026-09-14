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
