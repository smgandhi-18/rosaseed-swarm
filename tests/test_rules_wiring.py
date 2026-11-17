import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze import rule_for  # noqa: E402

from agents.conditions import CRITIC, PLANNER, rule_line, rule_text  # noqa: E402
from swarm.metrics import Refs  # noqa: E402
from swarm.queue import RunQueue  # noqa: E402
from swarm.space import DEFAULT  # noqa: E402
from swarm.store import Store  # noqa: E402
from swarm.tools import Budget, Context, ToolBox  # noqa: E402

V2 = Refs({"A": 6.83, "B": 6.72}, {"A": 0.87753, "B": 0.87532}, 0.0067, rule="v2",
          conf_limit={"A": 617, "B": 728})
V1 = Refs({"A": 6.83, "B": 6.72}, {"A": 0.87753, "B": 0.87532}, 0.0067)


def test_rule_comes_from_condition_names():
    assert rule_for(["random", "single", "swarm"]) == "v1"
    assert rule_for(["random-v2", "swarm-v2-uninformed", "single-norepeat-v2"]) == "v2"
    with pytest.raises(SystemExit):
        rule_for(["random", "swarm-v2"])


def test_v2_needs_limits():
    with pytest.raises(ValueError):
        Refs({"A": 1, "B": 1}, {"A": 0.9, "B": 0.9}, 0.01, rule="v2")


def test_planner_and_critic_get_the_rule_only_in_v2():
    assert rule_line(V1) == ""     # round 1 prompts stay exactly as they ran
    assert "617" in rule_line(V2) and rule_text(V2) in rule_line(V2)
    assert "confident_errors" in PLANNER.format(budget=24, per=8, space="", rule_line=rule_line(V2))
    assert "confident_errors" in CRITIC.format(claims="", rule_line=rule_line(V2))


def gamed_measure(config, read_set, cpus, cfg, root):
    # Accuracy fine, 15000 confident errors: v1-valid, v2-invalid.
    return {"status": "ok", "wall_s": 3.4, "correct": 181000, "mapq0": 5000, "mapq0_correct": 1000,
            "total": 200000, "mapped_frac": 1.0, "threads": 6, "cpus": cpus, "binary": "x",
            "attempts": 1, "started": 0, "finished": 1}


def test_v2_tool_output_matches_rule(tmp_path):
    cfg = {"cpus": {"workers": ["6-11"]}, "n_workers": 1}
    store = Store(tmp_path / "s.sqlite")
    ctx = Context(cfg, tmp_path, store, RunQueue(cfg, tmp_path, store, gamed_measure), V2, "x-v2", 1)
    box = ToolBox(ctx, "a", Budget(2))
    r = json.loads(box.call("run_rosaseed", {"config": DEFAULT.to_dict()}))
    assert r["confident_errors"] == 15000 and r["confident_error_limit"] == 617 and r["valid"] is False
    ctx.refs = V1
    r = json.loads(box.call("run_rosaseed", {"config": {**DEFAULT.to_dict(), "k": 20}}))
    assert r["valid"] is True and "confident_errors" not in r


def test_nudge_names_a_tool_the_role_has(tmp_path):
    from agents.loop import nudge_text
    cfg = {"cpus": {"workers": ["6-11"]}, "n_workers": 1}
    store = Store(tmp_path / "s.sqlite")
    ctx = Context(cfg, tmp_path, store, RunQueue(cfg, tmp_path, store, gamed_measure), V2, "x-v2", 1)
    critic, searcher = ToolBox(ctx, "c", role="critic"), ToolBox(ctx, "s", Budget(3))
    tools = lambda b: {t["function"]["name"] for t in b.schemas()}
    assert "decide" in nudge_text(critic) and "submit_claim" not in nudge_text(critic)
    assert "decide" in tools(critic) and "submit_claim" in tools(searcher)
    assert "submit_claim" in nudge_text(searcher) and "Runs left: 3" in nudge_text(searcher)
