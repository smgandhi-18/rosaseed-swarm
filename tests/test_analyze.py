import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze import confident_wrong, label_claim, score_pair  # noqa: E402

from swarm.metrics import Refs  # noqa: E402

REFS = Refs({"A": 6.83, "B": 6.72}, {"A": 0.87753, "B": 0.87532}, 0.0067)


def row(**kw):
    r = {"status": "ok", "wall_s": 3.415, "correct": 180667, "mapq0_correct": 5147, "total": 200000,
         "mapped_frac": 1.0, "mapq0": 23963, "config_hash": "h", "read_set": "A"}
    r.update(kw)
    return r


def test_confident_wrong_matches_hand_count():
    # BWA-MEM2 on set A: 19322 wrong in total, 18973 of them MAPQ 0 -> 349 confident errors
    assert confident_wrong({"mapped_frac": 1.0, "total": 200000, "correct": 180678,
                            "mapq0": 24145, "mapq0_correct": 5172}) == 349


def test_label_uses_critic_rules():
    search = [row()]                      # speedup 2.0, valid
    ok = {"speedup": 2.0, "accuracy_pct": 87.76}
    assert label_claim(REFS, search, ok, "h", True) == []
    assert "speedup claimed" in label_claim(REFS, search, {**ok, "speedup": 2.015}, "h", True)[0]
    assert "never run" in label_claim(REFS, search, ok, "zzz", True)[0]
    assert "held-out" in label_claim(REFS, search, ok, "h", False)[-1]
    slow = [row(wall_s=6.80)]             # speedup 1.004, below the 1.007 gate
    assert any("not above" in p for p in
               label_claim(REFS, slow, {"speedup": 1.004, "accuracy_pct": 87.76}, "h", True))


def test_score_pair_uses_paired_default_and_checks_consistency():
    cand = [row(wall_s=3.0, read_set="B", correct=180107, mapq0_correct=5080)] * 3
    dflt = [row(wall_s=6.0, read_set="B")] * 3
    s = score_pair(REFS, cand, dflt)
    assert s["speedup_B"] == pytest.approx(2.0) and s["valid_B"]
    mixed = cand[:2] + [row(wall_s=3.0, read_set="B", correct=180108, mapq0_correct=5080)]
    assert not score_pair(REFS, mixed, dflt)["valid_B"]
    assert not score_pair(REFS, cand[:2] + [row(status="crash")], dflt)["valid_B"]


def test_plot_finishes_when_lines_end_at_the_same_value(tmp_path):
    from analyze import _plot
    flat = [[1.0] * 24] * 3
    _plot(tmp_path / "p.png", {"random-v2": [[1.0] * 23 + [1.1]] * 3, "single-v2": flat,
                               "swarm-v2": flat})
    assert (tmp_path / "p.png").stat().st_size > 0
