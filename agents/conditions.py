"""The three conditions: random search, single agent, swarm (planner, explorers, critic).

Every condition gets the same number of runs on read set A and the same model.
"""
from __future__ import annotations

import json
import random
import threading
from pathlib import Path

from agents.loop import run_agent
from swarm.llm import make_llm
from swarm.metrics import MARGIN
from swarm.space import CAP_VALUES, FIELDS, GAP_RANGE, GAP_STEP_RANGE, K_RANGE, PRECHAIN, \
    random_config
from swarm.tools import Budget, Context, ToolBox

SEARCHER = """You are an optimisation agent tuning RosaSeed, the seeding stage inside the \
BWA-MEM2 short-read aligner. Each run aligns 100,000 simulated read pairs from human \
chromosome 22 (read set A) with one configuration.

Goal: find the configuration with the highest speedup_vs_default that is valid. {rule_text} \
Timing noise is about {noise} %, so speedup differences below 0.01 mean nothing.

Rules:
- You have {budget} runs. Every run_rosaseed call costs one run, including repeats of a \
config already run. Configs that are malformed or outside your region are rejected free.
- Explore broadly first, then refine around the best valid results.
- When no runs are left, call submit_claim with your best VALID config and its speedup and \
accuracy copied exactly from the log.
- Answer with tool calls. Keep any text under 40 words."""

EXPLORER_EXTRA = """
You are {name}, one of 3 explorers working in parallel. You may only run configs inside \
your region: {region}
read_log shows the results of all explorers ("by" says who ran it). Use it to avoid \
repeating their runs and to learn which settings matter."""

PLANNER = """You coordinate 3 explorers tuning RosaSeed (seeding inside the BWA-MEM2 aligner) \
for speed at fixed accuracy, with {budget} runs in total ({per} each).{rule_line}

{space}
Split this space into 3 regions, one per explorer, so that together they cover the \
promising parts of the space with little overlap. A region restricts some fields: a list \
of allowed values for prechain, frc, early_exit or cap, or {{"min": a, "max": b}} for k, gap \
or gap_step. Fields you do not restrict are free.

Reply with JSON only:
{{"regions": [{{"name": "explorer1", "rationale": "...", "constraints": {{...}}}}, ...]}}"""

CRITIC = """You are the critic of a team that tuned RosaSeed for speed at fixed accuracy.{rule_line} \
The explorers submitted these claims:
{claims}

For every claim:
1. Use read_log to check that the claimed config was actually run and that the claimed \
speedup (within 0.01) and accuracy (within 0.01 points) match the log, and that it was valid.
2. Use verify_on_heldout (at most 3 calls in total) to re-run the most promising claims on \
held-out read set B. Reject a claim whose valid_B is false.
3. Reject claims whose speedup is not above 1.007 (within timing noise).
Then call decide for EVERY claim with accept or reject and a one-sentence reason."""


def rule_text(refs) -> str:
    """How validity is explained to the agents (must match swarm.metrics.Refs.valid)."""
    t = (f"A run is valid when its accuracy_pct is no more than {100 * MARGIN:g} percentage "
         f"points below BWA-MEM2's accuracy")
    if refs.rule == "v2":
        t += (f" AND its confident_errors (reads placed confidently in the wrong place) are at "
              f"most confident_error_limit ({refs.conf_limit['A']} on set A)")
    return t + "."


def noise_pct(refs) -> str:
    # Round 1 ran with "0.7"; round 2 uses the session floor measured in round 1 (~1 %).
    return "1" if refs.rule == "v2" else "0.7"


def rule_line(refs) -> str:
    """Validity rule for the planner and critic prompts. Round 1 (v1) and the first round-2
    swarm (kept as swarm-v2-uninformed) ran without it, so v1 keeps the original prompt."""
    return "" if refs.rule == "v1" else " A configuration only counts if it is valid. " + rule_text(refs)


def max_turns(cfg: dict, budget: int) -> int:
    """Turn limit scaled with the budget (about 2 turns per run plus slack)."""
    return max(cfg["llm"]["max_turns"], 2 * budget + 16)


def searcher_done(box: ToolBox) -> bool:
    return bool(box.claim_ids)


def make_context(cfg, root, store, queue, refs, condition, repeat) -> Context:
    return Context(cfg, Path(root), store, queue, refs, condition, repeat)


def run_random(ctx: Context, budget: int, seed: int):
    rng = random.Random(seed)
    for _ in range(budget):
        ctx.queue.run(random_config(rng), "A", {"condition": ctx.condition, "repeat": ctx.repeat,
                                                "proposer": "random", "purpose": "search"})


def run_single(ctx: Context, budget: int, seed: int, tdir: Path, refuse_repeats: bool = False):
    llm = make_llm(ctx.cfg["llm"], seed)
    box = ToolBox(ctx, "single", Budget(budget), refuse_repeats=refuse_repeats)
    system = SEARCHER.format(rule_text=rule_text(ctx.refs), noise=noise_pct(ctx.refs), budget=budget)
    run_agent(llm, system, "Start by calling get_search_space.", box, store=ctx.store,
              condition=ctx.condition, repeat=ctx.repeat, max_turns=max_turns(ctx.cfg, budget),
              transcript=tdir / f"{ctx.condition}_{ctx.repeat}_single.jsonl", done=searcher_done)


FALLBACK_REGIONS = [
    {"name": "explorer1", "rationale": "fallback: no pre-chain filter",
     "constraints": {"prechain": ["off"]}},
    {"name": "explorer2", "rationale": "fallback: early pre-chain trigger",
     "constraints": {"prechain": ["t50w60", "t50w80"]}},
    {"name": "explorer3", "rationale": "fallback: late pre-chain trigger",
     "constraints": {"prechain": ["t200w60", "t200w80"]}},
]


def _normalise_rule(field: str, rule):
    """Accept equivalent spellings: a bare value for a one-element list, "true"/"false"
    strings for booleans, and a {"min","max"} range for cap (expanded to allowed values)."""
    def conv(v):
        if field in ("frc", "early_exit") and isinstance(v, str) and v.lower() in ("true", "false"):
            return v.lower() == "true"
        return v
    if field == "cap" and isinstance(rule, dict):
        lo, hi = rule.get("min", CAP_VALUES[0]), rule.get("max", CAP_VALUES[-1])
        return [c for c in CAP_VALUES if lo <= c <= hi]
    if field in ("prechain", "frc", "early_exit", "cap"):
        if not isinstance(rule, list):
            rule = [rule]
        return [conv(v) for v in rule]
    return rule


def parse_regions(text: str) -> list[dict]:
    """Parse and check the planner's JSON; raise ValueError if unusable."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object found")
    regions = json.loads(text[start:end + 1])["regions"]
    if len(regions) != 3:
        raise ValueError(f"need 3 regions, got {len(regions)}")
    lists = {"prechain": PRECHAIN, "frc": [True, False], "early_exit": [True, False],
             "cap": CAP_VALUES}
    ranges = {"k": K_RANGE, "gap": GAP_RANGE, "gap_step": GAP_STEP_RANGE}
    for i, r in enumerate(regions):
        r["name"] = f"explorer{i + 1}"
        cons = r.get("constraints") or {}
        for f in list(cons):
            if f not in FIELDS:
                raise ValueError(f"unknown field {f}")
            cons[f] = _normalise_rule(f, cons[f])
        for f, rule in cons.items():
            if f in lists:
                if not isinstance(rule, list) or not rule or any(v not in lists[f] for v in rule):
                    raise ValueError(f"bad allowed list for {f}: {rule}")
            else:
                lo, hi = ranges[f]
                if not isinstance(rule, dict) or not lo <= rule.get("min", lo) <= rule.get("max", hi) <= hi:
                    raise ValueError(f"bad range for {f}: {rule}")
                rule.setdefault("min", lo)
                rule.setdefault("max", hi)
        r["constraints"] = cons
    return regions


def run_swarm(ctx: Context, budget: int, seed: int, tdir: Path, refuse_repeats: bool = False) -> dict:
    from swarm.space import describe_space
    per = budget // 3
    info = {"planner_fallback": False, "planner_attempts": []}

    # 1. Planner
    planner = make_llm(ctx.cfg["llm"], seed)
    prompt = PLANNER.format(budget=budget, per=per, space=describe_space(), rule_line=rule_line(ctx.refs))
    messages = [{"role": "user", "content": prompt}]
    regions = None
    for attempt in range(3):
        msg, usage = planner.chat(messages, json_only=True)
        ctx.store.add_llm_call(ctx.condition, ctx.repeat, "planner", usage["prompt_tokens"],
                               usage["completion_tokens"], usage["seconds"])
        try:
            regions = parse_regions(msg["content"])
            info["planner_attempts"].append({"raw": msg["content"], "error": None})
            break
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            info["planner_attempts"].append({"raw": msg["content"], "error": repr(e)})
            messages += [{"role": "assistant", "content": msg["content"]},
                         {"role": "user", "content": f"Invalid: {e}. Reply with the JSON only."}]
    if regions is None:
        regions, info["planner_fallback"] = FALLBACK_REGIONS, True
    info["regions"] = regions
    (tdir / f"{ctx.condition}_{ctx.repeat}_planner.json").write_text(json.dumps(info, indent=2))

    # 2. Explorers in parallel (runs still go through the single run queue)
    boxes = []
    threads = []
    for i, r in enumerate(regions):
        box = ToolBox(ctx, r["name"], Budget(per), region=r["constraints"],
                      refuse_repeats=refuse_repeats)
        boxes.append(box)
        system = SEARCHER.format(rule_text=rule_text(ctx.refs), noise=noise_pct(ctx.refs), budget=per) + EXPLORER_EXTRA.format(
            name=r["name"], region=json.dumps(r["constraints"]))
        llm = make_llm(ctx.cfg["llm"], seed * 100 + i)
        t = threading.Thread(target=run_agent, args=(llm, system, "Start by calling get_search_space.", box),
                             kwargs=dict(store=ctx.store, condition=ctx.condition, repeat=ctx.repeat,
                                         max_turns=max_turns(ctx.cfg, per),
                                         transcript=tdir / f"{ctx.condition}_{ctx.repeat}_{r['name']}.jsonl",
                                         done=searcher_done))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # 3. Critic: only the last claim of each explorer counts
    claims = []
    for box in boxes:
        if box.claim_ids:
            c = [x for x in ctx.store.claims(condition=ctx.condition, repeat=ctx.repeat)
                 if x["id"] == box.claim_ids[-1]][0]
            claims.append(c)
    info["final_claim_ids"] = [c["id"] for c in claims]
    if claims:
        text = "\n".join(f"- claim_id {c['id']} by {c['agent']}: config {c['config_json']}, "
                         f"claimed {c['claimed_json']}" for c in claims)
        critic_box = ToolBox(ctx, "critic", role="critic")
        ids = {c["id"] for c in claims}
        run_agent(make_llm(ctx.cfg["llm"], seed * 1000), CRITIC.format(claims=text, rule_line=rule_line(ctx.refs)),
                  "Check the claims now.", critic_box, store=ctx.store, condition=ctx.condition,
                  repeat=ctx.repeat, max_turns=20,
                  transcript=tdir / f"{ctx.condition}_{ctx.repeat}_critic.jsonl",
                  done=lambda b: ids <= b.decided)
    (tdir / f"{ctx.condition}_{ctx.repeat}_planner.json").write_text(json.dumps(info, indent=2))
    return info
