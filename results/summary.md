| Condition | Repeats | Runs used (real) | Verified speedup on B, mean (min-max) | Runs to reach it | Confident errors on B (final) | Wrong or missing claims | Critic caught / missed / false alarm | Wall s | Tokens in+out | Model s |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 3 | 72 (72) | 2.177 (2.125-2.253) | 8.3 (5.0-13.0) (n=3) | 3516 (3499-3542) | - | - | 127 (125-132) | 0 (0-0) | 0 (0-0) |
| single | 3 | 72 (3) | 1.837 (1.617-1.956) | 1.0 (1.0-1.0) (n=3) | 2575 (1787-2969) | 0 of 3 | - | 44 (43-45) | 98001 (96606-100772) | 39 (38-40) |
| swarm | 3 | 72 (63) | 2.087 (2.042-2.118) | 20.3 (18.0-24.0) (n=3) | 3319 (2950-3528) | 2 of 9 | 1 / 1 / 2 | 128 (119-139) | 82742 (78047-88442) | 77 (69-91) |

- Speedup is over default RosaSeed timed in alternation with each candidate on held-out set B (63 default runs, median 6.64 s). Noise floor = 2 SD of those default runs = 1.08 %. 1.000 means no config beat the default by more than the floor while staying valid (accuracy within 0.05 points of BWA-MEM2; rule v1).
- Confident errors (MAPQ > 0, wrong place) on B: BWA-MEM2 431, default RosaSeed 628. Rule v1 does not penalise them; they are reported so a config that trades correct MAPQ-0 reads for confident mistakes is visible.
- Wrong or missing claims use the critic's own rules (speedup within 0.01 and accuracy within 0.01 points of the log, valid, speedup above 1.007) plus validity on B; a claim that was never submitted counts as wrong.
- Set-A speedups (plot, agents' view) are relative to the calibration-time default, which drifted by about 2.5 % between calibration batches; use the set-B column for comparisons.
