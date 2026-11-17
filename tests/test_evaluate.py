from pathlib import Path

import pytest

from swarm.evaluate import evaluate_sam, parse_truth

TINY = Path(__file__).parent / "data" / "tiny.sam"


def test_parse_truth():
    assert parse_truth("chr22_1000_1449_0:0:0_0:0:0_0") == ("chr22", 1000, 1449)
    assert parse_truth("chrUn_KI270_7_99_1:0:0_0:2:0_1a") == ("chrUn_KI270", 7, 99)
    with pytest.raises(ValueError):
        parse_truth("read42")


def test_tiny_sam_known_answers():
    r = evaluate_sam(TINY)
    # 10 primary records (secondary and supplementary ignored), 1 unmapped,
    # wrong: off-by-21 and wrong chromosome.
    assert r["total"] == 10
    assert r["mapped"] == 9
    assert r["correct"] == 7
    assert r["accuracy"] == pytest.approx(0.7)
    assert r["mapped_frac"] == pytest.approx(0.9)
    # both wrong reads have MAPQ 60
    assert r["wrong_q30"] == 2
    # no MAPQ-0 reads in the tiny file
    assert r["mapq0"] == 0 and r["mapq0_correct"] == 0


def test_placement_noise_from_mapq0_reads():
    from swarm.evaluate import placement_noise
    # 24145 MAPQ-0 reads, 5172 placed correctly, 200000 reads in total
    r = {"total": 200000, "mapq0": 24145, "mapq0_correct": 5172}
    assert placement_noise(r) == pytest.approx(63.75 / 200000, rel=0.01)


def test_tolerance_is_inclusive():
    assert evaluate_sam(TINY, tol=21)["correct"] == 8
