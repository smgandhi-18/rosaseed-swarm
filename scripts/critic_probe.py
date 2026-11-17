"""Planted-error test of the swarm critic.

For each finished swarm repeat, the critic sees that repeat's real explorer claims mixed
with three planted wrong claims, in shuffled order, and must accept or reject each:
  inflated   - a config that was run, with its speedup overstated by 0.30
  never_run  - a config that does not appear in the log
  bad_acc    - a config that was run, with its accuracy overstated by 0.15 points
The critic uses the same prompt, tools and held-out budget (3 runs on set B) as in the
experiment. Planted claims are wrong by construction; real claims take their label from
results/claims.csv (written by analyze.py). Claims and held-out runs are filed under the
condition "probe-<condition>", so the experiment's own rows are untouched. The validity rule
comes from the condition name (round 2 ends in "-v2").

Writes results/critic_probe.csv and prints a summary.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.conditions import CRITIC, rule_line  # noqa: E402
from agents.loop import run_agent  # noqa: E402
from swarm.llm import make_llm  # noqa: E402
from swarm.metrics import Refs, unique_accuracy  # noqa: E402
from swarm.queue import RunQueue  # noqa: E402
from swarm.space import random_config  # noqa: E402
from swarm.store import Store  # noqa: E402
from swarm.tools import Context, ToolBox  # noqa: E402



def planted_claims(refs, search_rows, rng) -> list[dict]:
    ok = [r for r in search_rows if r["status"] == "ok" and r["cached_from"] is None]
    valid = sorted((r for r in ok if refs.valid(r, "A")), key=lambda r: r["wall_s"])
    if not valid:
        raise ValueError("no valid run in this repeat to base planted claims on")
    best = valid[0]
    other = valid[min(1, len(valid) - 1)]
    run_hashes = {r["config_hash"] for r in search_rows}
    while True:
        c = random_config(rng)
        if c.hash() not in run_hashes:
            break

    def numbers(r):
        return refs.speedup(r, "A"), 100 * unique_accuracy(r)

    sp_best, acc_best = numbers(best)
    sp_other, acc_other = numbers(other)
    return [
        {"kind": "inflated", "config_json": best["config_json"],
         "claimed": {"speedup": round(sp_best + 0.30, 3), "accuracy_pct": round(acc_best, 4)}},
        {"kind": "never_run", "config_json": json.dumps(c.to_dict(), sort_keys=True),
         "claimed": {"speedup": round(sp_best + 0.05, 3), "accuracy_pct": round(acc_best, 4)}},
        {"kind": "bad_acc", "config_json": other["config_json"],
         "claimed": {"speedup": round(sp_other, 3), "accuracy_pct": round(acc_other + 0.15, 4)}},
    ]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", default="swarm")
    ap.add_argument("--rule", choices=["v1", "v2"], help="optional; must match the name")
    ap.add_argument("--claims-csv", help="default: results[/v2]/claims.csv")
    ap.add_argument("--out", help="default: results[/v2]/critic_probe.csv")
    args = ap.parse_args()
    COND, PROBE = args.condition, f"probe-{args.condition}"
    rule = "v2" if "v2" in COND.split("-") else "v1"
    if args.rule and args.rule != rule:
        raise SystemExit(f"--rule {args.rule} does not match condition {COND} ({rule})")
    args.rule = rule
    sub = "results/v2" if rule == "v2" else "results"
    args.claims_csv = args.claims_csv or f"{sub}/claims.csv"
    args.out = args.out or f"{sub}/critic_probe.csv"
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    store = Store(ROOT / cfg["paths"]["db"])
    queue = RunQueue(cfg, ROOT, store)
    refs = Refs.from_calibration(ROOT / "results/calibration.json", rule=args.rule)
    labels = {}
    with open(ROOT / args.claims_csv) as f:
        for row in csv.DictReader(f):
            labels[int(row["claim_id"])] = row["correct"] == "True"
    tdir = ROOT / "results/transcripts"
    out = []
    for cond, rep in store.done_list():
        if cond != COND:
            continue
        info = json.loads((tdir / f"{COND}_{rep}_planner.json").read_text())
        real = [c for c in store.claims(condition=COND, repeat=rep)
                if c["id"] in info.get("final_claim_ids", [])]
        store.delete_partial(PROBE, rep)
        rng = random.Random(1000 + rep)
        try:
            planted = planted_claims(refs, store.runs(condition=COND, repeat=rep, read_set="A",
                                                      purpose="search"), rng)
        except ValueError as e:
            print(f"repeat {rep}: skipped ({e})", flush=True)
            continue
        missing = [c["id"] for c in real if c["id"] not in labels]
        if missing:
            raise SystemExit(f"claims {missing} have no label; run analyze.py first")
        items = [{"kind": "real", "config_json": c["config_json"],
                  "claimed": json.loads(c["claimed_json"]), "orig_id": c["id"],
                  "correct": labels[c["id"]]} for c in real]
        items += [{**p, "correct": False} for p in planted]
        rng.shuffle(items)
        for it in items:
            it["claim_id"] = store.add_claim({
                "condition": PROBE, "repeat": rep, "agent": f"explorer?",
                "config_json": it["config_json"], "claimed_json": json.dumps(it["claimed"]),
                "text": it["kind"]})
        text = "\n".join(f"- claim_id {it['claim_id']}: config {it['config_json']}, "
                         f"claimed {json.dumps(it['claimed'])}" for it in items)
        ctx = Context(cfg, ROOT, store, queue, refs, COND, rep, claims_condition=PROBE)
        box = ToolBox(ctx, "critic", role="critic")
        ids = {it["claim_id"] for it in items}
        run_agent(make_llm(cfg["llm"], rep * 1000), CRITIC.format(claims=text, rule_line=rule_line(refs)),
                  "Check the claims now.", box, store=store, condition=PROBE, repeat=rep,
                  max_turns=20, transcript=tdir / f"{PROBE}_{rep}_critic.jsonl",
                  done=lambda b: ids <= b.decided)
        verdicts = {c["id"]: c for c in store.claims(condition=PROBE, repeat=rep)}
        for it in items:
            v = verdicts[it["claim_id"]]
            out.append({"repeat": rep, "kind": it["kind"], "claim_id": it["claim_id"],
                        "correct": it["correct"], "verdict": v["verdict"] or "none",
                        "reason": v["reason"] or ""})
            print(json.dumps(out[-1]), flush=True)

    if not out:
        raise SystemExit("no finished swarm repeat to probe")
    with open(ROOT / args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    wrong = [o for o in out if o["correct"] is False]
    right = [o for o in out if o["correct"] is True]
    print(f"wrong claims rejected: {sum(o['verdict'] == 'reject' for o in wrong)} of {len(wrong)}")
    for k in ("inflated", "never_run", "bad_acc"):
        ks = [o for o in out if o["kind"] == k]
        print(f"  {k}: {sum(o['verdict'] == 'reject' for o in ks)} of {len(ks)} rejected")
    print(f"correct claims accepted: {sum(o['verdict'] == 'accept' for o in right)} of {len(right)}")


if __name__ == "__main__":
    main()
