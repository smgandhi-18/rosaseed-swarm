import json

import pytest

from swarm.llm import parse_ollama_response
from swarm.metrics import Refs
from swarm.queue import RunQueue
from swarm.space import DEFAULT
from swarm.store import Store
from swarm.tools import Budget, Context, ToolBox

CFG = {"cpus": {"workers": ["6-11", "12-17"]}, "n_workers": 1}


def fake_measure(config, read_set, cpus, cfg, root):
    fake_measure.calls += 1
    return {"status": "ok", "wall_s": 3.415 if config.k == 25 else 6.83, "correct": 180667,
            "mapq0_correct": 5147, "total": 200000, "accuracy": 0.9, "mapped_frac": 1.0,
            "wrong_q30": 1, "mapq0": 100, "threads": 6, "cpus": cpus, "binary": "x",
            "attempts": 1, "started": 0, "finished": 1}


@pytest.fixture
def box(tmp_path):
    fake_measure.calls = 0
    store = Store(tmp_path / "s.sqlite")
    refs = Refs({"A": 6.83, "B": 6.72}, {"A": 0.87753, "B": 0.87532}, 0.0067)
    ctx = Context(CFG, tmp_path, store, RunQueue(CFG, tmp_path, store, fake_measure), refs, "single", 1)
    return ToolBox(ctx, "agent", Budget(2))


def run(box, **change):
    return json.loads(box.call("run_rosaseed", {"config": {**DEFAULT.to_dict(), **change}}))


def test_run_reports_speedup_and_validity(box):
    r = run(box, k=25)
    assert r["speedup_vs_default"] == 2.0 and r["valid"] is True and r["runs_left"] == 1


def test_invalid_config_not_charged(box):
    r = run(box, k=99)
    assert r["charged"] is False and "k must be in 15..25" in r["error"]
    assert box.budget.left == 2 and fake_measure.calls == 0


def test_region_violation_not_charged(box):
    box.region = {"prechain": ["off"]}
    r = run(box)
    assert "outside your region" in r["error"] and box.budget.left == 2


def test_budget_exhausted(box):
    run(box)
    run(box, k=25)
    r = run(box, k=20)
    assert "exhausted" in r["error"] and fake_measure.calls == 2


def test_repeat_config_uses_cache_but_costs_a_run(box):
    run(box)
    r = run(box)
    assert fake_measure.calls == 1 and r["runs_left"] == 0 and "repeat" in r["note"]
    rows = box.ctx.store.runs()
    assert rows[1]["cached_from"] == rows[0]["id"]


def test_read_log_sorted_fastest_first(box):
    run(box)
    run(box, k=25)
    rows = json.loads(box.call("read_log", {}))["rows"]
    assert [r["config"]["k"] for r in rows] == [25, 19]


def test_claim_refused_while_runs_left(box):
    r = json.loads(box.call("submit_claim", {"config": DEFAULT.to_dict(), "claimed_speedup": 1.0,
                                             "claimed_accuracy_pct": 87.76, "reason": "x"}))
    assert "use them all" in r["error"] and box.ctx.store.claims() == []


def test_claim_recorded(box):
    box.budget.used = box.budget.total
    r = json.loads(box.call("submit_claim", {"config": DEFAULT.to_dict(), "claimed_speedup": 1.0,
                                             "claimed_accuracy_pct": 87.76, "reason": "x"}))
    assert r["claim_id"] == 1 and box.ctx.store.claims()[0]["agent"] == "agent"


def test_unknown_tool_and_bad_args(box):
    assert "unknown tool" in box.call("verify_on_heldout", {"config": {}})
    assert "bad arguments" in box.call("read_log", {"nope": 1})


def test_parse_ollama_response_string_arguments():
    data = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "run_rosaseed", "arguments": "{\"config\": {\"k\": 21}}"}}]},
        "prompt_eval_count": 10, "eval_count": 5, "total_duration": 2_000_000_000}
    msg, usage = parse_ollama_response(data, 9.9)
    assert msg["tool_calls"][0]["arguments"] == {"config": {"k": 21}}
    assert usage == {"prompt_tokens": 10, "completion_tokens": 5, "seconds": 2.0}


def test_refuse_repeats_variant(box):
    box.refuse_repeats = True
    run(box)
    r = run(box)
    assert r["charged"] is False and "already run" in r["error"] and box.budget.left == 1
