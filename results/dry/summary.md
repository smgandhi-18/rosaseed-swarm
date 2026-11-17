| Condition | Repeats | Verified speedup on B (mean, min-max) | Runs to reach it | Wrong claims | Critic caught / missed / false alarm | Wall s | Tokens (in+out) | Model s |
|---|---|---|---|---|---|---|---|---|
| dry-random | 1 | 2.043 | 6.0 | 0 of 0 | - | 34 | 0 | 0 |
| dry-single | 1 | 2.030 | 3.0 | 0 of 32 | - | 92 | 141305 | 78 |
| dry-swarm | 1 | 2.113 | 4.0 | 0 of 3 | 0 / 0 / 0 | 70 | 28160 | 56 |

Speedup is over default RosaSeed (B median 6.72 s). 1.000 means no config beat the default by more than the noise floor (0.67 %) while staying within 0.05 points of BWA-MEM2 accuracy.
