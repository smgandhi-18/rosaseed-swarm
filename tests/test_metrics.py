import json

import pytest

from swarm.metrics import MARGIN, Refs, unique_accuracy


@pytest.fixture
def refs(tmp_path):
    def entry(wall, acc, mapq0_correct):
        return {"wall_median": wall, "accuracy": acc, "total": 200000, "mapq0_correct": mapq0_correct}
    c = {"rs_default_A": entry(6.83, 0.903335, 5147), "rs_default_B": entry(6.72, 0.900535, 5080),
         "bwa_A": entry(11.70, 0.90339, 5172), "bwa_B": entry(11.07, 0.90173, 5282),
         "speedup_noise_floor": 0.0067}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c))
    return Refs.from_calibration(p)


def test_unique_accuracy():
    assert unique_accuracy({"correct": 180678, "mapq0_correct": 5172, "total": 200000}) == pytest.approx(0.87753)


def test_bwa_reference(refs):
    assert refs.bwa_acc["A"] == pytest.approx(175506 / 200000)
    assert refs.bwa_acc["B"] == pytest.approx(175064 / 200000)


def test_default_rosaseed_is_valid_on_both_sets(refs):
    assert refs.valid({"status": "ok", "correct": 180667, "mapq0_correct": 5147, "total": 200000}, "A")
    assert refs.valid({"status": "ok", "correct": 180107, "mapq0_correct": 5080, "total": 200000}, "B")


def test_margin_boundary(refs):
    need = round((refs.bwa_acc["A"] - MARGIN) * 200000)   # 175406 unique-correct reads
    assert refs.valid({"status": "ok", "correct": need, "mapq0_correct": 0, "total": 200000}, "A")
    assert not refs.valid({"status": "ok", "correct": need - 1, "mapq0_correct": 0, "total": 200000}, "A")


def test_crash_is_invalid_and_has_no_speedup(refs):
    assert not refs.valid({"status": "crash"}, "A")
    assert refs.speedup({"status": "crash"}, "A") is None
    assert refs.speedup({"status": "ok", "wall_s": 3.415}, "A") == pytest.approx(2.0)


# ---- v2 rule: also limit confident errors (MAPQ > 0, wrong place) ----
from swarm.metrics import CONF_MARGIN, confident_wrong  # noqa: E402


def _calib(tmp_path):
    def entry(wall, acc, mapq0, mapq0_correct):
        return {"wall_median": wall, "accuracy": acc, "total": 200000, "mapped_frac": 1.0,
                "mapq0": mapq0, "mapq0_correct": mapq0_correct}
    c = {"rs_default_A": entry(6.83, 0.903335, 23963, 5147), "rs_default_B": entry(6.72, 0.900535, 24345, 5080),
         "bwa_A": entry(11.70, 0.90339, 24145, 5172), "bwa_B": entry(11.07, 0.90173, 24505, 5282),
         "speedup_noise_floor": 0.0067}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c))
    return p


def test_confident_wrong_limits_from_default(tmp_path):
    r2 = Refs.from_calibration(_calib(tmp_path), rule="v2")
    assert r2.conf_limit == {"A": 517 + CONF_MARGIN, "B": 628 + CONF_MARGIN}


def test_v2_rejects_confident_mistakes_that_v1_accepts(tmp_path):
    p = _calib(tmp_path)
    v1, v2 = Refs.from_calibration(p), Refs.from_calibration(p, rule="v2")
    # A low-cap config: MAPQ>0 accuracy fine, but 3000 confident errors.
    gamed = {"status": "ok", "total": 200000, "mapped_frac": 1.0, "correct": 181000,
             "mapq0": 5000, "mapq0_correct": 1000}
    assert confident_wrong(gamed) == 200000 - 181000 - 4000
    assert v1.valid(gamed, "A") and not v2.valid(gamed, "A")
    default_a = {"status": "ok", "total": 200000, "mapped_frac": 1.0, "correct": 180667,
                 "mapq0": 23963, "mapq0_correct": 5147}
    assert v2.valid(default_a, "A")


def test_v2_boundary(tmp_path):
    v2 = Refs.from_calibration(_calib(tmp_path), rule="v2")
    base = {"status": "ok", "total": 200000, "mapped_frac": 1.0, "mapq0": 0, "mapq0_correct": 0}
    at = {**base, "correct": 200000 - v2.conf_limit["A"]}
    assert confident_wrong(at) == v2.conf_limit["A"] and v2.valid(at, "A")
    assert not v2.valid({**at, "correct": at["correct"] - 1}, "A")
