# Evaluation

ContextBridge uses two evaluation layers. The first is a deterministic retrieval regression suite;
the second is an end-to-end coding-agent study. Results from the first layer must not be reported
as coding-task success rates.

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

Record strict pass rate, hidden task-completion rate, decision adherence, regressions, completion
time, input tokens, repeated file reads/searches, and incorrect assumptions about prior decisions.
Keep failed runs and raw traces. This second layer is the evidence appropriate for claims about
cross-agent task completion.

The first twelve-run study used only the visible targeted tests. All conditions passed, so that
study has a ceiling effect: it can compare token use and exploration, but it cannot support a claim
that one context strategy produces better task outcomes. The V2 protocol below fixes that weakness.
It does not assume ContextBridge wins; the purpose of the experiment is to test that hypothesis.

### Prepare a run plan

For the reproducible built-in study, first create the deliberately incomplete fixture repository:

```bash
contextbridge experiment-fixture \
  --output /tmp/contextbridge-resume-fixture
```

This writes the repository, `/tmp/contextbridge-resume-fixture.tasks.json`, and a sibling
`/tmp/contextbridge-resume-fixture.hidden` evaluator directory. The fixture contains three
independent Python tasks covering refresh-token replay, cache invalidation ordering, and
configuration precedence. Each targeted test fails at the baseline by design. The generated
manifest pins the repository commit and each hidden evaluator's SHA-256. The evaluator is outside
the target repository and is omitted from Agent B's run card, so it cannot be read while solving the
task through normal repository exploration. Creating it is local-only and consumes no agent quota.

The task split is intentionally handoff-dependent. Stage A receives several accepted behavioral
requirements, implements only the common foundation, and is told not to copy the pending decisions
into repository comments or documentation. The visible tests cover that foundation; the hidden
evaluator checks the pending decisions. Therefore a no-context Agent B cannot recover the complete
specification merely by reading a conveniently explicit TODO, which was the main design flaw in the
first study. This models a common failure mode—accepted requirements living only in conversation—
without making the implementation itself artificially large.

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
also verifies that every hidden evaluator exists and matches its pinned SHA-256. It rejects branch
names, `HEAD`, abbreviated hashes, and changed evaluators, preventing either the baseline or grading
rules from moving between conditions. Do not spend agent quota until preflight passes.

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
and exactly one condition payload. Leave Agent B's changes uncommitted so the recorder can verify
that `HEAD` still identifies the shared Stage-A checkpoint:

- `no_context`: no earlier conversation or generated summary.
- `raw_history`: the complete permitted Agent A transcript.
- `one_shot_summary`: a summary produced with one pinned model, prompt, and token budget.
- `contextbridge`: the Context Pack produced by `contextbridge-handoff` and loaded through
  `contextbridge-resume`.

Keep model versions, reasoning settings, permissions, repository state, and timeouts fixed across
conditions. Do not retry only failed conditions.

### Record and aggregate results

Run Agent B with Codex's JSONL output enabled and retain that trace. Then record the run through the
CLI instead of hand-authoring JSONL:

```bash
contextbridge experiment-record \
  --plan experiments/plan.json \
  --checkpoints experiments/checkpoints.jsonl \
  --results experiments/results.jsonl \
  --run cli-precedence--contextbridge \
  --worktree /tmp/contextbridge-runs/01-cli-precedence--contextbridge-48898aa8 \
  --trace traces/cli-precedence--contextbridge.codex.jsonl \
  --model-b gpt-5.6-sol \
  --duration-seconds 133.4 \
  --repeated-exploration 0 \
  --incorrect-assumptions 0
```

The recorder verifies the run ID, checkpoint commit, exact condition input, and hidden-evaluator
hash before executing both the visible test command and hidden evaluator. The evaluator's final
stdout line must be a JSON object with `assertions_passed`, `assertions_total`,
`decision_checks_passed`, `decision_checks_total`, and `regressions`. Strict pass requires all
visible tests, all hidden behavior and decision checks, and zero regressions. Task completion and
decision adherence remain separate rates; they are not collapsed into an arbitrary weighted score.

The recorder derives reported tokens as uncached input plus output from the final `turn.completed`
usage event. It retains raw, cached, and output counts separately and writes SHA-256-addressed
evidence for the Codex trace, visible-test output, hidden-evaluator output, and final Git diff. Failed
runs are recorded rather than discarded. `repeated_exploration` counts file reads or searches that
repeat Agent A's documented exploration; `incorrect_assumptions` counts claims about prior work that
conflict with the pinned repository or Agent A trace. Those two judgment-based fields remain manual.

```bash
contextbridge experiment-report \
  --plan experiments/plan.json \
  --results experiments/results.jsonl \
  --output experiments/report.md
```

The reporter rejects duplicate and unknown run IDs, keeps missing runs visible, and aggregates
strict pass, task completion, decision adherence, regressions, duration, reported tokens, repeated
exploration, and incorrect assumptions by condition. It does not fill in missing results, combine
metrics with post-hoc weights, or calculate significance for a small resume-project sample.

### Observed V2 pilot snapshot

The repository includes a partial seven-run snapshot in
[`experiments/v2/partial-report.md`](../experiments/v2/partial-report.md). It already demonstrates
why graded outcomes matter: the no-context config run passed its visible tests but missed the hidden
empty-CLI decision (7/8 behavior assertions, 4/5 decisions), while both completed ContextBridge
runs passed all hidden checks. The snapshot stopped when the Codex account hit its usage limit during
run 8; it is explicitly incomplete and does not establish that ContextBridge is universally best.
