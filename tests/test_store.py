from swarm.store import Store


def _row(**kw):
    row = {"condition": "random", "repeat": 1, "proposer": "random", "read_set": "A",
           "purpose": "search", "config_json": "{}", "config_hash": "abc", "binary": "rs_x",
           "status": "ok", "wall_s": 10.0, "accuracy": 0.9}
    row.update(kw)
    return row


def test_roundtrip(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    i = s.add_run(_row())
    rows = s.runs(condition="random")
    assert len(rows) == 1 and rows[0]["id"] == i and rows[0]["wall_s"] == 10.0


def test_cache_hit_only_same_read_set(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    s.add_run(_row())
    assert s.cached("abc", "A", "random", 1)["wall_s"] == 10.0
    assert s.cached("abc", "B", "random", 1) is None
    assert s.cached("zzz", "A", "random", 1) is None


def test_cache_not_shared_across_conditions_or_repeats(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    s.add_run(_row())
    assert s.cached("abc", "A", "single", 1) is None
    assert s.cached("abc", "A", "random", 2) is None


def test_failed_runs_are_not_cached(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    s.add_run(_row(status="crash"))
    assert s.cached("abc", "A", "random", 1) is None


def test_resume_after_reopen(tmp_path):
    p = tmp_path / "r.sqlite"
    Store(p).add_run(_row())
    s2 = Store(p)
    s2.mark_done("random", 1)
    assert len(s2.runs()) == 1
    assert Store(p).is_done("random", 1) and not Store(p).is_done("random", 2)


def test_llm_totals(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    s.add_llm_call("swarm", 1, "explorer1", 100, 20, 1.5)
    s.add_llm_call("swarm", 1, "critic", 50, 10, 0.5)
    assert s.llm_totals("swarm", 1) == {"calls": 2, "prompt_tokens": 150,
                                        "completion_tokens": 30, "seconds": 2.0}


def test_delete_partial_only_touches_that_repeat(tmp_path):
    s = Store(tmp_path / "r.sqlite")
    s.add_run(_row())
    s.add_run(_row(repeat=2))
    s.add_llm_call("random", 1, "a", 1, 1, 1.0)
    s.delete_partial("random", 1)
    assert [r["repeat"] for r in s.runs()] == [2]
    assert s.llm_totals("random", 1)["calls"] == 0
