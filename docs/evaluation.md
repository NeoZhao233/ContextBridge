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

Each synthetic case contains three required project memories and two unrelated memories. The four
strategies receive the same underlying facts:

- `no_context` receives nothing.
- `raw_history` receives a verbose synthetic conversation containing every item.
- `one_shot_summary` receives a fixture-authored short summary that retains two required items and
  one distractor. It is a stable regression baseline, not the output of a claimed production model.
- `contextbridge` ranks all candidate memories for the task and selects three under a 500-token
  memory budget. Its measured payload is the rendered Context Pack, including instructions and
  provenance.

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

This benchmark verifies ranking, budgeting, provenance retention, packaging, and CLI output. Because
the cases and summary baseline are controlled fixtures, it does not establish real-world superiority.

## End-to-end study

The resume-project experiment should use ten small two-stage coding tasks. Agent A performs the first
stage and Agent B resumes under one randomly assigned condition: no context, raw history, a summary
from a fixed model and prompt, or ContextBridge. Pin model versions and settings, rotate condition
order, and start each run from the same Git commit.

Record task-test pass rate, completion time, input tokens, repeated file reads/searches, and incorrect
assumptions about prior decisions. Keep failed runs and raw traces. This second layer is the evidence
appropriate for claims about cross-agent task completion.
