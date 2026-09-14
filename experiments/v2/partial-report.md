# V2 graded outcome pilot (partial)

Completed: 7/12. Conditions with fewer than three runs are not imputed.

| Condition | Runs | Strict pass | Task outcome | Decision | Regressions | Seconds | Reported tokens | Re-exploration | Wrong assumptions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_context | 1/3 | 0.0% | 87.5% | 80.0% | 0.0 | 126.2 | 32915.0 | 5.0 | 1.0 |
| raw_history | 2/3 | 100.0% | 100.0% | 100.0% | 0.0 | 121.5 | 29648.5 | 4.5 | 0.0 |
| one_shot_summary | 2/3 | 100.0% | 100.0% | 100.0% | 0.0 | 106.0 | 27550.0 | 4.0 | 0.0 |
| contextbridge | 2/3 | 100.0% | 100.0% | 100.0% | 0.0 | 143.1 | 31477.0 | 4.0 | 0.0 |

The no-context config run passed its visible tests but scored 7/8 hidden behavior assertions and 4/5
decision checks: it inferred that an empty CLI value should be ignored, while the accepted
specification required an explicit clear. This is a concrete outcome failure that the first study
could not observe.

The two ContextBridge runs completed all hidden checks and used fewer reported tokens than the raw
history condition in the same partial sample. One-shot summaries used the fewest tokens so far and
also passed; this pilot therefore supports a nuanced trade-off, not a preselected winner.

Missing runs: `auth-refresh--contextbridge`, `auth-refresh--no_context`,
`auth-refresh--raw_history`, `cache-race--no_context`, and `cli-precedence--one_shot_summary`.
