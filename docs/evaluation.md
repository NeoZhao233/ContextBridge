# Evaluation

ContextBridge uses two evaluation layers. The first is a deterministic retrieval regression suite;
the second is a planned end-to-end coding-agent study. Results from the first layer must not be
reported as coding-task success rates.

## Offline retrieval benchmark

Run the bundled ten-case dataset:

```bash
contextbridge evaluate
contextbridge evaluate --format json --output evaluation.json
```

Each synthetic case contains three required project outcomes and two unrelated outcomes. The five
strategies receive the same underlying facts:

- `no_context` receives nothing.
- `raw_history` receives a verbose synthetic conversation containing every item.
- `one_shot_summary` receives a fixture-authored short summary that retains two required items and
  one distractor. It is a stable regression baseline, not the output of a claimed production model.
- `contextbridge` ranks all candidate memories for the task and selects three under a 500-token
  memory budget. Its measured payload is the rendered Context Pack, including instructions and
  provenance.
- `offline_excerpts` starts with zero structured memories. It ranks synthetic user/assistant events
  with event FTS and fills the same 500-token budget with attributed raw excerpts, exercising the
  no-API fallback used when the original agent cannot summarize its session.

Metrics are macro-averaged across cases. Required recall is the fraction of required memory IDs
selected. Precision is the relevant fraction of selected IDs. Source coverage is the fraction of
required IDs retained with source attribution. Token counts use ContextBridge's provider-neutral
Latin/CJK estimator and are totals across all cases.

Current expected output:

| Strategy | Required recall | Precision | Source coverage | Total tokens |
|---|---:|---:|---:|---:|
| no_context | 0.0% | 0.0% | 0.0% | 0 |
| raw_history | 100.0% | 60.0% | 100.0% | 6228 |
| one_shot_summary | 66.7% | 66.7% | 0.0% | 522 |
| contextbridge | 100.0% | 100.0% | 100.0% | 2086 |
| offline_excerpts | 100.0% | 75.0% | 100.0% | 4879 |

The offline-excerpt path retains every required outcome while using 21.7% fewer tokens than the full
synthetic history, but it is less precise and substantially larger than structured ContextBridge
memory. This is the intended emergency fallback tradeoff, not evidence that extraction is
unnecessary.

This benchmark verifies ranking, budgeting, provenance retention, packaging, and CLI output.
Because the cases and summary baseline are controlled fixtures, it does not establish real-world
superiority.

## End-to-end study

The resume-project experiment should start with three small two-stage coding tasks, each repeated
under all four conditions for twelve runs. Five tasks and twenty runs are a useful stretch goal;
forty or more runs are outside the MVP budget. Agent A performs the first stage and Agent B resumes
with no context, raw history, a summary from a fixed model and prompt, or ContextBridge. Pin model
versions and settings, randomize condition order, and start each run from the same Git commit.

Record task-test pass rate, completion time, input tokens, repeated file reads/searches, and incorrect
assumptions about prior decisions. Keep failed runs and raw traces. This second layer is the evidence
appropriate for claims about cross-agent task completion.

### Prepare a run plan

Copy `experiments/tasks.example.json`, replace its repository and commit placeholders, and add or
remove tasks to match the desired budget. The minimal example has three tasks and therefore produces
twelve runs; five tasks produce twenty runs.

```bash
contextbridge experiment-plan \
  --manifest experiments/tasks.json \
  --seed 42 \
  --output experiments/plan.json
```

Every task appears once under each condition. The seed randomizes run order reproducibly. A run must
start from its task's pinned `base_commit` in a fresh worktree or disposable checkout.

For each assignment, let Agent A execute `stage_a_prompt`, then start a fresh Agent B session with
`stage_b_prompt` and exactly one condition payload:

- `no_context`: no earlier conversation or generated summary.
- `raw_history`: the complete permitted Agent A transcript.
- `one_shot_summary`: a summary produced with one pinned model, prompt, and token budget.
- `contextbridge`: the Context Pack produced by `contextbridge-handoff` and loaded through
  `contextbridge-resume`.

Keep model versions, reasoning settings, permissions, repository state, and timeouts fixed across
conditions. Do not retry only failed conditions.

### Record and aggregate results

Write one JSON object per completed run using `experiments/results.example.jsonl` as the schema. A
trace path should point to retained raw evidence. `repeated_exploration` counts file reads or searches
that repeat Agent A's documented exploration; `incorrect_assumptions` counts claims about prior work
that conflict with the pinned repository or Agent A trace.

```bash
contextbridge experiment-report \
  --plan experiments/plan.json \
  --results experiments/results.jsonl \
  --output experiments/report.md
```

The reporter rejects duplicate and unknown run IDs, keeps missing runs visible, and aggregates pass
rate, duration, input tokens, repeated exploration, and incorrect assumptions by condition. It does
not fill in missing results or calculate significance for a small resume-project sample.
