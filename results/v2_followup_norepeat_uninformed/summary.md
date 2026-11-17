| Condition | Repeats | Runs used (real) | Verified speedup on B, mean (min-max) | Runs to reach it | Confident errors on B (final) | Wrong or missing claims | Critic caught / missed / false alarm | Wall s | Tokens in+out | Model s |
|---|---|---|---|---|---|---|---|---|---|---|
| single-norepeat-v2 | 3 | 22 (22) | 1.000 (1.000-1.000) | n/a (n=0) | n/a | 3 of 3 | - | 116 (101-139) | 223840 (219133-232721) | 84 (83-85) |
| swarm-norepeat-v2-uninformed | 3 | 71 (71) | 1.019 (1.000-1.058) | 24.0 (n=1) | 718 | 8 of 9 | 7 / 0 / 0 | 148 (139-159) | 121762 (70962-204997) | 84 (62-119) |

- Speedup is over default RosaSeed timed in alternation with each candidate on held-out set B (9 default runs, median 6.72 s). Noise floor = 2 SD of those default runs = 0.49 %. 1.000 means no config beat the default by more than the floor while staying valid (accuracy within 0.05 points of BWA-MEM2 and confident errors at most 728 on B; rule v2).
- Confident errors (MAPQ > 0, wrong place) on B: BWA-MEM2 431, default RosaSeed 628. Rule v2 caps them at 728 on B.
- Wrong or missing claims use the critic's own rules (speedup within 0.01 and accuracy within 0.01 points of the log, valid, speedup above 1.007) plus validity on B; a claim that was never submitted counts as wrong.
- Set-A speedups (plot, agents' view) are relative to the calibration-time default, which drifted by about 2.5 % between calibration batches; use the set-B column for comparisons.
