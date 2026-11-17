"""Score every (condition, repeat) from the store, never from agent claims.

Q1 search quality (same rule for every condition): take the 3 fastest valid configs on
set A; run each 3 times on held-out set B, alternating with default RosaSeed
(default, candidate, default, candidate, ...) so each speedup is measured against a
default timed minutes apart. The noise floor is 2 SD of all those default runs over the
whole analysis session, so it includes slow drift and not only run-to-run jitter. Keep
the fastest candidate that is valid on B and faster than the default by more than the
floor.

Q2 reliability: label each agent claim with the same rules the critic was given
(config really run, speedup within 0.01 and accuracy within 0.01 points of the log,
valid, speedup above 1.007) plus validity on held-out B. Missing claims count as wrong
answers. Score the swarm critic against those labels.

Also reported for each final config: confident errors on B (wrong placements with
MAPQ > 0), next to BWA-MEM2 and the default (rule v1 ignores them; rule v2 caps them).
The rule comes from the condition names: round-2 conditions end in "-v2".

Writes results/results.csv, results/claims.csv, results/summary.md, results/best_so_far.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from swarm.metrics import MARGIN, Refs, confident_wrong, unique_accuracy  # noqa: E402
from swarm.queue import RunQueue  # noqa: E402
from swarm.space import DEFAULT, validate  # noqa: E402
from swarm.store import Store  # noqa: E402

TOP = 3
B_PAIRS = 3
SPEED_TOL = 0.01     # same tolerances and gate as in the critic's prompt
ACC_TOL_PP = 0.01
SPEED_GATE = 1.007
EXPECTED_CLAIMS = {"single": 1, "swarm": 3}


def paired_b(store, queue, cond, rep, cfg_json: str, n: int) -> tuple[list[dict], list[dict]]:
    """n candidate runs on B, each preceded by a default run (resumable)."""
    c = validate(json.loads(cfg_json))
    tag = f"final-default:{c.hash()}"
    def have():
        cand = [r for r in store.runs(condition=cond, repeat=rep, read_set="B", purpose="final")
                if r["config_hash"] == c.hash()]
        dflt = store.runs(condition=cond, repeat=rep, read_set="B", purpose=tag)
        return cand, dflt
    cand, dflt = have()
    for i in range(n):
        meta = {"condition": cond, "repeat": rep, "proposer": "harness"}
        if len(dflt) <= i:
            dflt.append(queue.run(DEFAULT, "B", {**meta, "purpose": tag}, use_cache=False))
        if len(cand) <= i:
            cand.append(queue.run(c, "B", {**meta, "purpose": "final"}, use_cache=False))
    return cand[:n], dflt[:n]


def score_pair(refs, cand, dflt) -> dict:
    ok_c = [r for r in cand if r["status"] == "ok"]
    ok_d = [r for r in dflt if r["status"] == "ok"]
    if len(ok_c) < len(cand) or not ok_c or not ok_d:
        return {"valid_B": False, "speedup_B": None, "note": "a held-out run failed"}
    same = len({(r["correct"], r["mapq0"], r["mapq0_correct"], r["total"]) for r in ok_c}) == 1
    return {
        "valid_B": same and all(refs.valid(r, "B") for r in ok_c),
        "speedup_B": st.median(r["wall_s"] for r in ok_d) / st.median(r["wall_s"] for r in ok_c),
        "acc_B": unique_accuracy(ok_c[0]),
        "confident_wrong_B": confident_wrong(ok_c[0]),
        "note": "" if same else "accuracy differed between identical runs",
        "default_walls": [r["wall_s"] for r in ok_d],
    }


def label_claim(refs, search, claimed: dict, cfg_hash: str, valid_b: bool) -> list[str]:
    problems = []
    logged = [r for r in search if r["config_hash"] == cfg_hash and r["status"] == "ok"]
    if not logged:
        return ["config never run"] + ([] if valid_b else ["invalid on held-out B"])
    r = logged[0]
    sp, acc = refs.speedup(r, "A"), 100 * unique_accuracy(r)
    try:
        if abs(float(claimed["speedup"]) - sp) > SPEED_TOL:
            problems.append(f"speedup claimed {claimed['speedup']} vs logged {sp:.3f}")
        if abs(float(claimed["accuracy_pct"]) - acc) > ACC_TOL_PP:
            problems.append(f"accuracy claimed {claimed['accuracy_pct']} vs logged {acc:.4f}")
    except (TypeError, ValueError, KeyError):
        problems.append("claimed numbers missing or not numeric")
    if not refs.valid(r, "A"):
        problems.append("invalid on A")
    if sp <= SPEED_GATE:
        problems.append(f"speedup {sp:.3f} not above {SPEED_GATE}")
    if not valid_b:
        problems.append("invalid on held-out B")
    return problems


def rule_for(conditions: list[str]) -> str:
    """The validity rule is part of each condition's name (round 2 = "-v2")."""
    rules = {"v2" if "v2" in c.split("-") else "v1" for c in conditions}
    if len(rules) != 1:
        raise SystemExit(f"conditions mix rule v1 and v2: {conditions}")
    return rules.pop()


def analyze_one(store, queue, refs, cond, rep) -> dict:
    search = store.runs(condition=cond, repeat=rep, read_set="A", purpose="search")
    curve, best, first_seen = [], 1.0, {}
    for i, r in enumerate(search, 1):
        first_seen.setdefault(r["config_hash"], i)
        if refs.valid(r, "A"):
            best = max(best, refs.speedup(r, "A"))
        curve.append(best)

    # Q1 candidates (final pick needs the session-wide noise floor, done in main)
    valid = {}
    for r in search:
        if r["cached_from"] is None and refs.valid(r, "A"):
            sp = refs.speedup(r, "A")
            if r["config_hash"] not in valid or sp > valid[r["config_hash"]][0]:
                valid[r["config_hash"]] = (sp, r["config_json"])
    candidates = []
    for h, (sp_a, cj) in sorted(valid.items(), key=lambda kv: -kv[1][0])[:TOP]:
        s = score_pair(refs, *paired_b(store, queue, cond, rep, cj, B_PAIRS))
        candidates.append({**s, "config_json": cj, "speedup_A": sp_a, "hash": h})

    # Q2: only the claims that count (last claim per agent; for the swarm, the final ones)
    base = cond.split("-")[0]
    all_claims = store.claims(condition=cond, repeat=rep)
    final_ids = set(_final_claim_ids(cond, rep))
    if base == "swarm" and final_ids:
        counted = [c for c in all_claims if c["id"] in final_ids]
    else:
        last = {}
        for c in all_claims:
            last[c["agent"]] = c
        counted = list(last.values())
    claims_out = []
    for c in counted:
        cfg_hash = validate(json.loads(c["config_json"])).hash()
        lab = store.runs(condition=cond, repeat=rep, read_set="B", purpose="label")
        lab = [r for r in lab if r["config_hash"] == cfg_hash]
        if not lab:
            lab = [queue.run(validate(json.loads(c["config_json"])), "B",
                             {"condition": cond, "repeat": rep, "proposer": "harness",
                              "purpose": "label"}, use_cache=False)]
        valid_b = lab[0]["status"] == "ok" and refs.valid(lab[0], "B")
        problems = label_claim(refs, search, json.loads(c["claimed_json"]), cfg_hash, valid_b)
        claims_out.append({"condition": cond, "repeat": rep, "rule": refs.rule, "claim_id": c["id"], "agent": c["agent"],
                           "config": c["config_json"], "claimed": c["claimed_json"],
                           "correct": not problems, "problems": "; ".join(problems),
                           "critic_verdict": c["verdict"] or "", "critic_reason": c["reason"] or ""})

    llm = store.llm_totals(cond, rep)
    done = store.done_row(cond, rep)
    expected = EXPECTED_CLAIMS.get(base, 0)
    row = {
        "condition": cond, "repeat": rep, "rule": refs.rule, "search_runs": len(search),
        "real_runs": sum(r["cached_from"] is None for r in search),
        "crashes": sum(r["status"] != "ok" for r in search),
        "best_speedup_A": round(curve[-1], 4) if curve else None,
        "wall_s": round(done["wall_s"], 1) if done and done["wall_s"] else None,
        "llm_calls": llm["calls"], "prompt_tokens": llm["prompt_tokens"],
        "completion_tokens": llm["completion_tokens"], "model_s": round(llm["seconds"], 1),
        "claims_expected": expected, "claims_submitted": len(claims_out),
        "wrong_claims": sum(not c["correct"] for c in claims_out) + max(0, expected - len(claims_out)),
    }
    if base == "swarm":
        info = _planner_info(cond, rep)
        row["planner_fallback"] = info.get("planner_fallback")
        ex = claims_out
        row["critic_caught"] = sum(c["critic_verdict"] == "reject" and not c["correct"] for c in ex)
        row["critic_missed"] = sum(c["critic_verdict"] == "accept" and not c["correct"] for c in ex)
        row["critic_false_alarm"] = sum(c["critic_verdict"] == "reject" and c["correct"] for c in ex)
        row["critic_correct_accept"] = sum(c["critic_verdict"] == "accept" and c["correct"] for c in ex)
        row["critic_undecided"] = sum(not c["critic_verdict"] for c in ex)
        acc = [c for c in ex if c["critic_verdict"] == "accept"]
        pick = max(acc, key=_claimed_speed, default=None)
        nocritic = max(ex, key=_claimed_speed, default=None)
        row["answer_with_critic_correct"] = bool(pick and pick["correct"])
        row["answer_without_critic_correct"] = bool(nocritic and nocritic["correct"])
    elif base == "single":
        row["answer_without_critic_correct"] = bool(claims_out and claims_out[-1]["correct"])
    return {"row": row, "claims": claims_out, "curve": curve, "candidates": candidates,
            "first_seen": first_seen}


def _claimed_speed(c) -> float:
    try:
        return float(json.loads(c["claimed"])["speedup"])
    except (TypeError, ValueError, KeyError):
        return 0.0


def _planner_info(cond, rep) -> dict:
    p = ROOT / f"results/transcripts/{cond}_{rep}_planner.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _final_claim_ids(cond, rep) -> list[int]:
    return _planner_info(cond, rep).get("final_claim_ids", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", nargs="+", default=["random", "single", "swarm"],
                    help="exact condition names to include")
    ap.add_argument("--out", default="results")
    ap.add_argument("--rule", choices=["v1", "v2"], help="optional; must match the names")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    store = Store(ROOT / cfg["paths"]["db"])
    queue = RunQueue(cfg, ROOT, store)
    rule = rule_for(args.conditions)
    if args.rule and args.rule != rule:
        raise SystemExit(f"--rule {args.rule} does not match the condition names ({rule})")
    args.rule = rule
    refs = Refs.from_calibration(ROOT / "results/calibration.json", rule=rule)
    calib = json.loads((ROOT / "results/calibration.json").read_text())
    out = ROOT / args.out
    out.mkdir(exist_ok=True)

    results = []
    for cond, rep in store.done_list():
        if cond in args.conditions:
            results.append(analyze_one(store, queue, refs, cond, rep))
            print(f"analysed {cond} {rep}", flush=True)

    # Session-wide noise floor from every paired default run on B.
    dwalls = [w for res in results for c in res["candidates"] for w in c.get("default_walls", [])]
    floor = 2 * st.stdev(dwalls) / st.median(dwalls) if len(dwalls) > 1 else refs.noise_floor
    for res in results:
        row = res["row"]
        ok = [c for c in res["candidates"] if c["valid_B"] and c["speedup_B"] and c["speedup_B"] > 1 + floor]
        final = max(ok, key=lambda c: c["speedup_B"], default=None)
        row["verified_speedup_B"] = round(final["speedup_B"], 4) if final else 1.0
        row["verified_config"] = final["config_json"] if final else "default (nothing beat it on B)"
        row["runs_to_best"] = res["first_seen"].get(final["hash"]) if final else None
        row["final_confident_wrong_B"] = final["confident_wrong_B"] if final else None
        row["candidates_failing_B"] = sum(not c["valid_B"] for c in res["candidates"])

    rows = [r["row"] for r in results]
    claims = [c for r in results for c in r["claims"]]
    refs_b = {"bwa": confident_wrong({**calib["bwa_B"], "correct": round(calib["bwa_B"]["accuracy"] * calib["bwa_B"]["total"])}),
              "default": confident_wrong({**calib["rs_default_B"], "correct": round(calib["rs_default_B"]["accuracy"] * calib["rs_default_B"]["total"])})}
    _write_csv(out / "results.csv", rows)
    _write_csv(out / "claims.csv", claims)
    _summary(out / "summary.md", rows, floor, dwalls, refs_b, args.conditions, refs)
    _plot(out / "best_so_far.png", {c: [r["curve"] for r in results if r["row"]["condition"] == c]
                                    for c in args.conditions},
          title=f"Search progress, rule {args.rule}")


def _write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _fmt(vals, nd=2):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "n/a"
    m = st.mean(vals)
    return f"{m:.{nd}f} ({min(vals):.{nd}f}-{max(vals):.{nd}f})" if len(vals) > 1 else f"{m:.{nd}f}"


def _summary(path, rows, floor, dwalls, refs_b, conds, refs):
    lines = [
        "| Condition | Repeats | Runs used (real) | Verified speedup on B, mean (min-max) | "
        "Runs to reach it | Confident errors on B (final) | Wrong or missing claims | "
        "Critic caught / missed / false alarm | Wall s | Tokens in+out | Model s |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in conds:
        rs = [r for r in rows if r["condition"] == c]
        if not rs:
            continue
        critic = "-"
        if "critic_caught" in rs[0]:
            critic = " / ".join(str(sum(r[k] for r in rs)) for k in
                                ("critic_caught", "critic_missed", "critic_false_alarm"))
        n_rtb = sum(r["runs_to_best"] is not None for r in rs)
        claims = "-" if not rs[0]["claims_expected"] else \
            f"{sum(r['wrong_claims'] for r in rs)} of {sum(r['claims_expected'] for r in rs)}"
        lines.append(
            f"| {c} | {len(rs)} | {sum(r['search_runs'] for r in rs)} "
            f"({sum(r['real_runs'] for r in rs)}) | {_fmt([r['verified_speedup_B'] for r in rs], 3)} | "
            f"{_fmt([r['runs_to_best'] for r in rs], 1)} (n={n_rtb}) | "
            f"{_fmt([r['final_confident_wrong_B'] for r in rs], 0)} | {claims} | {critic} | "
            f"{_fmt([r['wall_s'] for r in rs], 0)} | "
            f"{_fmt([r['prompt_tokens'] + r['completion_tokens'] for r in rs], 0)} | "
            f"{_fmt([r['model_s'] for r in rs], 0)} |")
    lines += [
        "",
        f"- Speedup is over default RosaSeed timed in alternation with each candidate on held-out "
        f"set B ({len(dwalls)} default runs, median {st.median(dwalls):.2f} s). "
        f"Noise floor = 2 SD of those default runs = {100 * floor:.2f} %. 1.000 means no config "
        f"beat the default by more than the floor while staying valid "
        f"({'accuracy within %g points of BWA-MEM2 and confident errors at most %d on B' % (100 * MARGIN, refs.conf_limit['B']) if refs.rule == 'v2' else 'accuracy within %g points of BWA-MEM2' % (100 * MARGIN)}; rule {refs.rule})."
        if dwalls else "- No held-out runs.",
        f"- Confident errors (MAPQ > 0, wrong place) on B: BWA-MEM2 {refs_b['bwa']}, default "
        f"RosaSeed {refs_b['default']}. "
        + (f"Rule v2 caps them at {refs.conf_limit['B']} on B." if refs.rule == "v2" else
           "Rule v1 does not penalise them; they are reported so a config that trades correct "
           "MAPQ-0 reads for confident mistakes is visible."),
        "- Wrong or missing claims use the critic's own rules (speedup within 0.01 and accuracy "
        "within 0.01 points of the log, valid, speedup above 1.007) plus validity on B; a claim "
        "that was never submitted counts as wrong.",
        "- Set-A speedups (plot, agents' view) are relative to the calibration-time default, "
        "which drifted by about 2.5 % between calibration batches; use the set-B column for "
        "comparisons.",
    ]
    Path(path).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


COLORS = {"random": "#2a78d6", "single": "#eb6834", "swarm": "#1baf7a"}   # fixed per method
STYLES = {"random": ("-", "o"), "single": ("--", "s"), "swarm": (":", "^")}
LABELS = {"random": "Random search", "single": "Single agent", "swarm": "Swarm"}


def _label(cond: str) -> str:
    base, *variants = cond.split("-")
    extra = [{"norepeat": "repeats refused", "uninformed": "planner not told the rule"}[v]
             for v in variants if v in ("norepeat", "uninformed")]
    return LABELS.get(base, base) + (f" ({', '.join(extra)})" if extra else "")


def _plot(path, curves, title="Search progress"):
    curves = {c: cs for c, cs in curves.items() if cs}
    if not curves:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    n = max(len(c) for cs in curves.values() for c in cs)
    ends = []
    for cond, cs in curves.items():
        base = cond.split("-")[0]
        cs = [c + [c[-1]] * (n - len(c)) if c else [1.0] * n for c in cs]  # carry best forward
        xs = list(range(1, n + 1))
        mean = [st.mean(c[i] for c in cs) for i in range(n)]
        lo = [min(c[i] for c in cs) for i in range(n)]
        hi = [max(c[i] for c in cs) for i in range(n)]
        ls, mk = STYLES.get(base, ("-", "o"))
        color = COLORS.get(base, "#52514e")
        ax.fill_between(xs, lo, hi, step="post", alpha=0.12, color=color, linewidth=0)
        ax.plot(xs, mean, drawstyle="steps-post", linestyle=ls, linewidth=2, color=color,
                marker=mk, markevery=list(range(3, n, 4)), markersize=7,
                markeredgecolor="white", markeredgewidth=1.2, label=f"{_label(cond)} (n={len(cs)})")
        ends.append((mean[-1], LABELS.get(base, base)))
    # direct labels at the right edge, nudged apart so they never overlap
    span = ax.get_ylim()[1] - ax.get_ylim()[0]
    placed = []
    for value, lab in sorted(ends):
        # one step, no loop: a while-loop here never ended when two lines finished at the
        # same value (floating-point rounding kept the gap a hair under the minimum)
        y = max(value, placed[-1] + 0.06 * span) if placed else value
        placed.append(y)
        ax.annotate(f"{lab} {value:.2f}x", xy=(n, y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color="#0b0b0b")
    ax.axhline(1.0, color="#9a9890", lw=0.8, ls="--")
    ax.set_xlim(1, n)
    ax.set_xlabel("RosaSeed runs on set A")
    ax.set_ylabel("Best valid speedup over default so far")
    ax.set_title(f"{title} (line = mean, band = min-max over repeats)", fontsize=11)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best", fontsize=9)
    fig.tight_layout()
    fig.subplots_adjust(right=0.76)
    fig.savefig(path, dpi=150)


if __name__ == "__main__":
    main()
