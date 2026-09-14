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

For the reproducible built-in study, first create the deliberately incomplete fixture repository:

```bash
contextbridge experiment-fixture \
  --output /tmp/contextbridge-resume-fixture
```

This writes the repository and `/tmp/contextbridge-resume-fixture.tasks.json`. The fixture contains
three independent Python tasks covering refresh-token replay, cache invalidation ordering, and
configuration precedence. Each targeted test fails at the baseline by design. The generated manifest
pins all tasks to the exact initial commit and lives outside the repository, leaving its checkout
clean. Creating it is local-only and consumes no agent quota.

Alternatively, copy `experiments/tasks.example.json`, replace its repository and commit placeholders,
and add or remove tasks to match the desired budget. Three tasks produce twelve runs; five tasks
produce twenty runs.

```bash
contextbridge experiment-plan \
  --manifest /tmp/contextbridge-resume-fixture.tasks.json \
  --seed 42 \
  --output experiments/plan.json

contextbridge experiment-preflight --plan experiments/plan.json
```

Every task appears once under each condition. The seed randomizes run order reproducibly. A run must
start from its task's pinned `base_commit` in a fresh worktree or disposable checkout.
`experiment-preflight` resolves every repository and base commit without executing task code. It
also rejects branch names, `HEAD`, and abbreviated hashes: the manifest must contain the full object
ID reported by Git so later runs cannot silently move to a different baseline. Do not spend agent
quota until preflight passes.

### Record one Stage-A checkpoint per task

For a matched comparison, run Agent A once per task rather than once per condition. Start from the
task's `base_commit`, execute `stage_a_prompt`, and commit only Agent A's repository changes on the
disposable worktree. Export the complete permitted transcript, produce the fixed one-shot summary,
and generate and validate the Context Pack. Then record their paths with the full checkpoint commit:

```bash
contextbridge experiment-checkpoint \
  --plan experiments/plan.json \
  --output experiments/checkpoints.jsonl \
  --task cli-precedence \
  --commit <full-stage-a-commit> \
  --agent-a claude-code \
  --model-a deepseek-v4-flash \
  --transcript traces/cli-precedence.raw.md \
  --summary traces/cli-precedence.summary.md \
  --context-pack traces/cli-precedence.contextbridge.md
```

The command verifies that the checkpoint resolves to a full Git object ID, descends from the task's
base commit, and has all three condition artifacts. It rejects a second checkpoint for the same
task. Keep generated handoff artifacts outside the checkpoint commit so all four worktrees receive
only their assigned condition input.

Use the plan order instead of choosing conditions manually. Prepare each run in its own worktree:

```bash
contextbridge experiment-prepare \
  --plan experiments/plan.json \
  --checkpoints experiments/checkpoints.jsonl \
  --results experiments/results.jsonl \
  --worktree-root /tmp/contextbridge-runs
```

The command runs preflight, skips recorded run IDs, and creates a clean detached Git worktree at the
task's Stage-A checkpoint. It injects exactly one `.contextbridge/condition.md` for raw history,
one-shot summary, or ContextBridge, and injects no file for `no_context`. The run card tells the
operator not to rerun Agent A. It refuses to overwrite an existing run directory or place the
worktree root inside the fixture repository. Omit `--results` before the first run. When every
assignment is recorded, it reports completion instead of silently cycling back. Use
`experiment-next` instead when only a read-only preview of the next card is needed. Omitting
`--checkpoints` retains the earlier independent-pair workflow, but that mode does not control Agent A
variance and should not be used for the reported comparison.

Preserve the run trace and diff before removing a completed worktree. Then use ordinary
`git worktree remove <run-directory>` from the fixture repository; avoid `--force`, which can discard
an uncommitted agent result.

For each assignment, start a fresh Agent B session from the prepared checkpoint with `stage_b_prompt`
and exactly one condition payload:

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
