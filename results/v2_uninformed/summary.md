| Condition | Repeats | Runs used (real) | Verified speedup on B, mean (min-max) | Runs to reach it | Confident errors on B (final) | Wrong or missing claims | Critic caught / missed / false alarm | Wall s | Tokens in+out | Model s |
|---|---|---|---|---|---|---|---|---|---|---|
| random-v2 | 3 | 72 (72) | 1.093 (1.078-1.101) | 11.3 (6.0-20.0) (n=3) | 713 (709-717) | - | - | 128 (125-133) | 0 (0-0) | 0 (0-0) |
| single-v2 | 3 | 72 (15) | 1.000 (1.000-1.000) | n/a (n=0) | n/a | 3 of 3 | - | 61 (46-69) | 97786 (90763-106190) | 39 (37-41) |
| swarm-v2-uninformed | 3 | 72 (63) | 1.020 (1.000-1.059) | 22.0 (n=1) | 722 | 8 of 9 | 8 / 0 / 0 | 129 (122-141) | 83533 (76362-88548) | 74 (69-82) |

- Speedup is over default RosaSeed timed in alternation with each candidate on held-out set B (36 default runs, median 6.63 s). Noise floor = 2 SD of those default runs = 1.01 %. 1.000 means no config beat the default by more than the floor while staying valid (accuracy within 0.05 points of BWA-MEM2 and confident errors at most 728 on B; rule v2).
- Confident errors (MAPQ > 0, wrong place) on B: BWA-MEM2 431, default RosaSeed 628. Rule v2 caps them at 728 on B.
- Wrong or missing claims use the critic's own rules (speedup within 0.01 and accuracy within 0.01 points of the log, valid, speedup above 1.007) plus validity on B; a claim that was never submitted counts as wrong.
- Set-A speedups (plot, agents' view) are relative to the calibration-time default, which drifted by about 2.5 % between calibration batches; use the set-B column for comparisons.
