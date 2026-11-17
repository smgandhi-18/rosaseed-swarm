"""Tools the agents call. Every tool returns a short JSON string for the model."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .metrics import MARGIN, Refs, confident_wrong, unique_accuracy
from .space import FIELDS, describe_space, validate


class Budget:
    """Thread-safe run counter. Explorers of one swarm each get their own."""

    def __init__(self, total: int):
        self.total, self.used = total, 0
        self._lock = threading.Lock()

    def charge(self) -> bool:
        with self._lock:
            if self.used >= self.total:
                return False
            self.used += 1
            return True

    @property
    def left(self) -> int:
        return self.total - self.used


@dataclass
class Context:
    cfg: dict
    root: Path
    store: object
    queue: object
    refs: Refs
    condition: str
    repeat: int
    # Where claims, verdicts and held-out runs are filed. Defaults to `condition`; the
    # critic probe sets it so planted claims never mix with the experiment's own rows.
    claims_condition: str | None = None

    @property
    def cc(self) -> str:
        return self.claims_condition or self.condition


def region_violation(region: dict | None, cfg_dict: dict) -> str | None:
    """Region = {field: [allowed values]} or {field: {"min": a, "max": b}}."""
    if not region:
        return None
    for f, rule in region.items():
        v = cfg_dict[f]
        if isinstance(rule, dict):
            if not rule.get("min", v) <= v <= rule.get("max", v):
                return f"{f}={v} is outside your region ({rule['min']}..{rule['max']})"
        elif v not in rule:
            return f"{f}={v!r} is outside your region (allowed: {rule})"
    return None


def _fmt_row(refs: Refs, row: dict) -> dict:
    sp = refs.speedup(row, row["read_set"])
    return {
        "by": row["proposer"],
        "config": json.loads(row["config_json"]),
        "status": row["status"],
        "speedup_vs_default": round(sp, 3) if sp else None,
        "accuracy_pct": round(100 * unique_accuracy(row), 4) if row["status"] == "ok" else None,
        **({"confident_errors": confident_wrong(row) if row["status"] == "ok" else None}
           if refs.rule == "v2" else {}),
        "valid": refs.valid(row, row["read_set"]),
    }


class ToolBox:
    def __init__(self, ctx: Context, agent: str, budget: Budget | None = None,
                 region: dict | None = None, role: str = "searcher", critic_budget: int = 3,
                 refuse_repeats: bool = False):
        self.ctx, self.agent, self.budget, self.region, self.role = ctx, agent, budget, region, role
        # Follow-up variant only: an exact repeat of a config already in the team's log is
        # refused without cost instead of being served from cache for one run.
        self.refuse_repeats = refuse_repeats
        self.critic_budget = Budget(critic_budget)
        self.claim_ids: list[int] = []
        self.decided: set[int] = set()

    # ---- schemas -------------------------------------------------------------------
    def schemas(self) -> list[dict]:
        config_schema = {
            "type": "object",
            "description": "RosaSeed configuration with fields " + ", ".join(FIELDS),
            "properties": {
                "prechain": {"type": "string"}, "frc": {"type": "boolean"},
                "early_exit": {"type": "boolean"}, "k": {"type": "integer"},
                "cap": {"type": "integer"}, "gap": {"type": "integer"},
                "gap_step": {"type": "integer"},
            },
            "required": FIELDS,
        }
        read_log = _tool("read_log", "Results logged so far by your team, fastest first.", {
            "top": {"type": "integer", "description": "how many rows (default 10)"},
            "only_valid": {"type": "boolean", "description": "only rows that are valid"},
        }, [])
        if self.role == "critic":
            return [read_log,
                    _tool("verify_on_heldout", "Run a config on held-out read set B (max 3 calls).",
                          {"config": config_schema}, ["config"]),
                    _tool("decide", "Accept or reject one claim.", {
                        "claim_id": {"type": "integer"},
                        "verdict": {"type": "string", "enum": ["accept", "reject"]},
                        "reason": {"type": "string"}}, ["claim_id", "verdict", "reason"])]
        return [
            _tool("get_search_space", "Describe the configuration fields and allowed values.", {}, []),
            _tool("run_rosaseed", "Align read set A with a config. Costs one run.",
                  {"config": config_schema}, ["config"]),
            read_log,
            _tool("submit_claim", "Submit your best valid config and its numbers from the log.", {
                "config": config_schema,
                "claimed_speedup": {"type": "number"},
                "claimed_accuracy_pct": {"type": "number"},
                "reason": {"type": "string"}},
                ["config", "claimed_speedup", "claimed_accuracy_pct", "reason"]),
        ]

    # ---- dispatch -------------------------------------------------------------------
    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, f"t_{name}", None)
        allowed = {s["function"]["name"] for s in self.schemas()}
        if fn is None or name not in allowed:
            return _j(error=f"unknown tool {name!r}; available: {sorted(allowed)}")
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return _j(error=f"bad arguments for {name}: {e}")
        except Exception as e:  # a tool error must never kill an agent thread
            return _j(error=f"{name} failed: {e!r}")

    def _config(self, config) -> tuple[object, str | None]:
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                return None, "config must be a JSON object"
        try:
            c = validate(config)
        except ValueError as e:
            return None, str(e)
        return c, None

    def t_get_search_space(self) -> str:
        text = describe_space()
        if self.region:
            text += f"\nYOUR REGION (other values are rejected): {json.dumps(self.region)}\n"
        return _j(space=text, budget_left=self.budget.left if self.budget else None)

    def t_run_rosaseed(self, config=None) -> str:
        c, err = self._config(config)
        if err:
            return _j(error=err, charged=False)
        bad = region_violation(self.region, c.to_dict())
        if bad:
            return _j(error=bad, charged=False)
        if self.refuse_repeats:
            seen = self.ctx.store.runs(condition=self.ctx.condition, repeat=self.ctx.repeat,
                                       purpose="search", config_hash=c.hash())
            if seen:
                prev = _fmt_row(self.ctx.refs, seen[0])
                return _j(error="this exact config was already run (by "
                          f"{prev['by']}): speedup {prev['speedup_vs_default']}, "
                          + (f"confident_errors {prev['confident_errors']}, "
                             if "confident_errors" in prev else "")
                          + f"valid {prev['valid']}. Try a different config.", charged=False,
                          runs_left=self.budget.left)
        if not self.budget.charge():
            return _j(error="run budget exhausted; call submit_claim now", runs_left=0)
        row = self.ctx.queue.run(c, "A", {"condition": self.ctx.condition, "repeat": self.ctx.repeat,
                                          "proposer": self.agent, "purpose": "search"})
        out = _fmt_row(self.ctx.refs, row)
        out.pop("by")
        if row.get("cached_from") is not None:
            out["note"] = "repeat of an earlier run (same result, still cost one run)"
        out["bwa_accuracy_pct"] = round(100 * self.ctx.refs.bwa_acc["A"], 4)
        if self.ctx.refs.rule == "v2":
            out["confident_error_limit"] = self.ctx.refs.conf_limit["A"]
        out["runs_left"] = self.budget.left
        return json.dumps(out)

    def t_read_log(self, top=10, only_valid=False) -> str:
        rows = [r for r in self.ctx.store.runs(condition=self.ctx.condition, repeat=self.ctx.repeat,
                                               purpose="search")]
        rows = [_fmt_row(self.ctx.refs, r) for r in rows]
        if only_valid:
            rows = [r for r in rows if r["valid"]]
        rows.sort(key=lambda r: -(r["speedup_vs_default"] or 0))
        return json.dumps({"rows": rows[: int(top or 10)], "total_rows": len(rows),
                           "accuracy_bar_pct": round(100 * (self.ctx.refs.bwa_acc["A"] - MARGIN), 4),
                           **({"confident_error_limit": self.ctx.refs.conf_limit["A"]}
                              if self.ctx.refs.rule == "v2" else {})})

    def t_submit_claim(self, config=None, claimed_speedup=None, claimed_accuracy_pct=None,
                       reason="") -> str:
        c, err = self._config(config)
        if err:
            return _j(error=err)
        if self.budget and self.budget.left:
            return _j(error=f"you still have {self.budget.left} runs; use them all before submit_claim")
        cid = self.ctx.store.add_claim({
            "condition": self.ctx.cc, "repeat": self.ctx.repeat, "agent": self.agent,
            "config_json": json.dumps(c.to_dict(), sort_keys=True),
            "claimed_json": json.dumps({"speedup": claimed_speedup,
                                        "accuracy_pct": claimed_accuracy_pct}),
            "text": str(reason)[:1000]})
        self.claim_ids.append(cid)
        return _j(ok="claim recorded; you are done", claim_id=cid)

    def t_verify_on_heldout(self, config=None) -> str:
        c, err = self._config(config)
        if err:
            return _j(error=err)
        if not self.critic_budget.charge():
            return _j(error="held-out budget exhausted (3 runs)")
        row = self.ctx.queue.run(c, "B", {"condition": self.ctx.cc, "repeat": self.ctx.repeat,
                                          "proposer": self.agent, "purpose": "critic"},
                                 use_cache=False)
        sp = self.ctx.refs.speedup(row, "B")
        return json.dumps({
            "status": row["status"],
            "speedup_vs_default_B": round(sp, 3) if sp else None,
            "accuracy_pct_B": round(100 * unique_accuracy(row), 4) if row["status"] == "ok" else None,
            "accuracy_bar_pct_B": round(100 * (self.ctx.refs.bwa_acc["B"] - MARGIN), 4),
            **({"confident_errors_B": confident_wrong(row) if row["status"] == "ok" else None,
                "confident_error_limit_B": self.ctx.refs.conf_limit["B"]}
               if self.ctx.refs.rule == "v2" else {}),
            "valid_B": self.ctx.refs.valid(row, "B"),
            "heldout_runs_left": self.critic_budget.left})

    def t_decide(self, claim_id=None, verdict=None, reason="") -> str:
        ids = {c["id"] for c in self.ctx.store.claims(condition=self.ctx.cc,
                                                      repeat=self.ctx.repeat)}
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return _j(error="claim_id must be an integer")
        if claim_id not in ids or verdict not in ("accept", "reject"):
            return _j(error=f"claim_id must be one of {sorted(ids)} and verdict accept|reject")
        self.ctx.store.set_claim_verdict(claim_id, verdict, str(reason)[:1000])
        self.decided.add(claim_id)
        return _j(ok=f"claim {claim_id}: {verdict}")


def _tool(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required}}}


def _j(**kw) -> str:
    return json.dumps(kw)
