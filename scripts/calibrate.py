"""Baselines and timing noise (checkpoint 1).

1. BWA-MEM2 and default RosaSeed on sets A and B (5 runs each, worker 1 alone).
2. Default RosaSeed 10 runs on worker 1 alone, then 10 runs on worker 1 while
   worker 2 runs the same job at the same time. If the busy neighbour changes the
   runtime by less than the run-to-run noise, the experiment uses 2 workers.

Writes results/calibration.json and results/baseline.md.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from swarm.evaluate import placement_noise  # noqa: E402
from swarm.measure import measure  # noqa: E402
from swarm.space import DEFAULT  # noqa: E402


def summarize(runs: list[dict]) -> dict:
    w = [r["wall_s"] for r in runs]
    first = runs[0]
    return {
        "n": len(runs), "wall_median": st.median(w), "wall_sd": st.stdev(w) if len(w) > 1 else 0.0,
        "wall_min": min(w), "wall_max": max(w),
        "peak_rss_gib": max(r["peak_rss_kb"] for r in runs) / 2**20,
        "accuracy": first["accuracy"], "mapped_frac": first["mapped_frac"],
        "wrong_q30": first["wrong_q30"], "mapq0": first["mapq0"],
        "mapq0_correct": first["mapq0_correct"], "total": first["total"],
        "accuracy_identical_across_runs": len({r["correct"] for r in runs}) == 1,
    }


def main():
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    w1, w2 = cfg["cpus"]["workers"]
    out = {"threads": cfg["threads"], "workers": cfg["cpus"]["workers"]}

    for read_set in ["A", "B"]:
        for name, c in [("bwa", None), ("rs_default", DEFAULT)]:
            runs = [measure(c, read_set, w1, cfg, ROOT) for _ in range(5)]
            assert all(r["status"] == "ok" for r in runs), runs
            out[f"{name}_{read_set}"] = summarize(runs)
            print(name, read_set, out[f"{name}_{read_set}"], flush=True)

    alone = [measure(DEFAULT, "A", w1, cfg, ROOT) for _ in range(10)]
    busy = []
    with ThreadPoolExecutor(2) as ex:
        for _ in range(10):
            f1 = ex.submit(measure, DEFAULT, "A", w1, cfg, ROOT)
            f2 = ex.submit(measure, DEFAULT, "A", w2, cfg, ROOT)
            busy.append(f1.result())
            f2.result()
    out["noise_alone"] = summarize(alone)
    out["noise_busy_neighbour"] = summarize(busy)
    d = out["noise_busy_neighbour"]["wall_median"] - out["noise_alone"]["wall_median"]
    sd = out["noise_alone"]["wall_sd"]
    out["neighbour_effect_s"] = d
    out["recommended_workers"] = 2 if abs(d) < sd else 1
    out["speedup_noise_floor"] = 2 * sd / out["noise_alone"]["wall_median"]
    for s in ["A", "B"]:
        out[f"accuracy_delta_{s}"] = 2 * placement_noise(out[f"bwa_{s}"])

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/calibration.json").write_text(json.dumps(out, indent=2))
    write_markdown(out)


def write_markdown(o: dict):
    lines = [
        f"# Baselines and noise (chr22, 100k pairs, -t {o['threads']}, one die per worker)", "",
        "| Aligner | Set | Wall s (median of 5) | SD | Peak RSS GiB | Accuracy % | "
        "Mapped % | Wrong with MAPQ>=30 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in ["A", "B"]:
        for name, label in [("bwa", "BWA-MEM2"), ("rs_default", "RosaSeed default")]:
            r = o[f"{name}_{s}"]
            lines.append(f"| {label} | {s} | {r['wall_median']:.2f} | {r['wall_sd']:.2f} | "
                         f"{r['peak_rss_gib']:.2f} | {100*r['accuracy']:.4f} | "
                         f"{100*r['mapped_frac']:.2f} | {r['wrong_q30']} |")
    a, b = o["noise_alone"], o["noise_busy_neighbour"]
    lines += [
        "", "## Timing noise (default RosaSeed, set A, 10 runs each)", "",
        f"- worker alone: median {a['wall_median']:.2f} s, SD {a['wall_sd']:.3f} s, "
        f"range {a['wall_min']:.2f}-{a['wall_max']:.2f}",
        f"- neighbour die busy: median {b['wall_median']:.2f} s, SD {b['wall_sd']:.3f} s, "
        f"range {b['wall_min']:.2f}-{b['wall_max']:.2f}",
        f"- neighbour effect: {o['neighbour_effect_s']:+.3f} s -> use {o['recommended_workers']} worker(s)",
        f"- speedup noise floor (2 SD / median): {100*o['speedup_noise_floor']:.2f} %",
        f"- accuracy tolerance (2 SD of MAPQ-0 placement, from BWA-MEM2): "
        f"A {100*o['accuracy_delta_A']:.4f} pp, B {100*o['accuracy_delta_B']:.4f} pp",
    ]
    (ROOT / "results/baseline.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
