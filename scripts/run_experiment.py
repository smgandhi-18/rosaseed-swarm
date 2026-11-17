"""Run conditions x repeats. Resumable: a finished (condition, repeat) is skipped.

Example:
  python scripts/run_experiment.py --conditions random single swarm --repeats 1 2 3
  python scripts/run_experiment.py --budget 6 --prefix dry- --repeats 1     # dry run
"""
from __future__ import annotations

import argparse
import fcntl
import random
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.conditions import make_context, run_random, run_single, run_swarm  # noqa: E402
from swarm.metrics import Refs  # noqa: E402
from swarm.queue import RunQueue  # noqa: E402
from swarm.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", nargs="+", default=["random", "single", "swarm"])
    ap.add_argument("--repeats", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--prefix", default="", help="condition name prefix, e.g. dry-")
    ap.add_argument("--rule", default="v1", choices=["v1", "v2"],
                    help="validity rule; v2 runs are stored as <condition>-v2")
    ap.add_argument("--fixed-order", action="store_true",
                    help="run conditions in the given order (default: seeded shuffle per repeat)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    budget = args.budget or cfg["budget"]
    store = Store(ROOT / cfg["paths"]["db"])
    queue = RunQueue(cfg, ROOT, store)
    refs = Refs.from_calibration(ROOT / "results/calibration.json", rule=args.rule)
    tdir = ROOT / "results/transcripts"
    tdir.mkdir(parents=True, exist_ok=True)

    suffix = "-v2" if args.rule == "v2" else ""
    names = [c + suffix if not c.endswith(suffix) else c for c in args.conditions]
    for cond in names:                      # check every name before touching the store
        base, *variants = cond.split("-")
        if base not in ("random", "single", "swarm") or set(variants) - {"norepeat", "v2"}:
            raise SystemExit(f"unknown condition {cond}")
        if ("v2" in variants) != (args.rule == "v2"):
            raise SystemExit(f"{cond}: name and --rule disagree")
    lock = open(ROOT / "work" / "experiment.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another run_experiment.py is running")
    for rep in args.repeats:
        order = list(args.conditions)
        if not args.fixed_order:
            random.Random(1000 + rep).shuffle(order)   # so slow drift does not favour one condition
        for cond in order:
            cond = cond + suffix if not cond.endswith(suffix) else cond
            name = args.prefix + cond
            if store.is_done(name, rep):
                print(f"skip {name} repeat {rep} (done)", flush=True)
                continue
            if store.runs(condition=name, repeat=rep):
                # A partial agent run cannot be resumed mid-conversation: discard and redo.
                print(f"{name} repeat {rep} was interrupted; rerunning it", flush=True)
                store.delete_partial(name, rep)
            ctx = make_context(cfg, ROOT, store, queue, refs, name, rep)
            t0 = time.time()
            base, *variants = cond.split("-")          # e.g. "single-norepeat-v2"
            norepeat = "norepeat" in variants
            if base == "random":
                run_random(ctx, budget, seed=rep)
            elif base == "single":
                run_single(ctx, budget, seed=rep, tdir=tdir, refuse_repeats=norepeat)
            elif base == "swarm":
                run_swarm(ctx, budget, seed=rep, tdir=tdir, refuse_repeats=norepeat)
            store.mark_done(name, rep, wall_s=time.time() - t0)
            n = len(store.runs(condition=name, repeat=rep, purpose="search"))
            print(f"{name} repeat {rep}: {n} search runs, {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
