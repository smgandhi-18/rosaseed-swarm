"""Does model inference slow an alignment? (review finding: in the swarm, other explorers
generate while one explorer's alignment runs; in the other conditions nothing overlaps.)

Default RosaSeed on set A, 8 runs alone and 8 runs while 3 threads keep the model busy,
alternating alone/busy. Writes results/llm_overlap.json.
"""
from __future__ import annotations

import json
import statistics as st
import sys
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from swarm.llm import make_llm  # noqa: E402
from swarm.measure import measure  # noqa: E402
from swarm.space import DEFAULT  # noqa: E402

PROMPT = [{"role": "user", "content": "List 40 facts about DNA sequencing, one per line."}]


def main():
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    cpus = cfg["cpus"]["workers"][0]
    alone, busy = [], []
    for i in range(8):
        alone.append(measure(DEFAULT, "A", cpus, cfg, ROOT)["wall_s"])
        stop = threading.Event()

        def generate(seed):
            llm = make_llm(cfg["llm"], seed)
            while not stop.is_set():
                llm.chat(PROMPT)

        threads = [threading.Thread(target=generate, args=(100 * i + j,)) for j in range(3)]
        for t in threads:
            t.start()
        busy.append(measure(DEFAULT, "A", cpus, cfg, ROOT)["wall_s"])
        stop.set()
        for t in threads:
            t.join()
    out = {"alone": alone, "busy": busy,
           "alone_median": st.median(alone), "busy_median": st.median(busy),
           "alone_sd": st.stdev(alone), "effect_pct": 100 * (st.median(busy) / st.median(alone) - 1)}
    (ROOT / "results/llm_overlap.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
