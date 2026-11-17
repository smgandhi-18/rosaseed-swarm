# Baselines and noise (chr22, 100k pairs, -t 6, one die per worker)

| Aligner | Set | Wall s (median of 5) | SD | Peak RSS GiB | Accuracy % | Mapped % | Wrong with MAPQ>=30 |
|---|---|---|---|---|---|---|---|
| BWA-MEM2 | A | 11.70 | 0.11 | 1.60 | 90.3390 | 100.00 | 5 |
| RosaSeed default | A | 6.83 | 0.04 | 3.54 | 90.3335 | 100.00 | 50 |
| BWA-MEM2 | B | 11.07 | 0.04 | 1.61 | 90.1730 | 100.00 | 6 |
| RosaSeed default | B | 6.72 | 0.04 | 3.55 | 90.0535 | 100.00 | 69 |

## Timing noise (default RosaSeed, set A, 10 runs each)

- worker alone: median 6.67 s, SD 0.022 s, range 6.63-6.70
- neighbour die busy: median 6.76 s, SD 0.059 s, range 6.66-6.82
- neighbour effect: +0.100 s -> use 1 worker(s)
- speedup noise floor (2 SD / median): 0.67 %
- accuracy tolerance (2 SD of MAPQ-0 placement, from BWA-MEM2): A 0.0638 pp, B 0.0644 pp
