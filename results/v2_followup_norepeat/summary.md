| Condition | Repeats | Runs used (real) | Verified speedup on B, mean (min-max) | Runs to reach it | Confident errors on B (final) | Wrong or missing claims | Critic caught / missed / false alarm | Wall s | Tokens in+out | Model s |
|---|---|---|---|---|---|---|---|---|---|---|
| single-norepeat-v2 | 3 | 22 (22) | 1.000 (1.000-1.000) | n/a (n=0) | n/a | 3 of 3 | - | 116 (101-139) | 223840 (219133-232721) | 84 (83-85) |
| swarm-norepeat-v2 | 3 | 70 (70) | 1.000 (1.000-1.000) | n/a (n=0) | n/a | 9 of 9 | 4 / 0 / 0 | 162 (139-174) | 178062 (106765-220949) | 115 (72-137) |

- No held-out runs.
- Confident errors (MAPQ > 0, wrong place) on B: BWA-MEM2 431, default RosaSeed 628. Rule v2 caps them at 728 on B.
- Wrong or missing claims use the critic's own rules (speedup within 0.01 and accuracy within 0.01 points of the log, valid, speedup above 1.007) plus validity on B; a claim that was never submitted counts as wrong.
- Set-A speedups (plot, agents' view) are relative to the calibration-time default, which drifted by about 2.5 % between calibration batches; use the set-B column for comparisons.
