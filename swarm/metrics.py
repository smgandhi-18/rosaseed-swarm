"""Reference numbers and the validity rules shared by agents and analysis.

v2 (added after the first experiment showed every search method exploiting v1): a
config must ALSO make at most CONF_MARGIN more confident errors (MAPQ > 0, wrong place)
than default RosaSeed on the same read set. Low --rs-cap settings turn MAPQ-0 repeat reads
into confident guesses; v1 rewarded the ~20 % that land right and ignored the rest.


Accuracy = reads placed within the tolerance AND with MAPQ > 0, divided by all reads.
MAPQ-0 reads are excluded from the numerator because the aligner itself reports that it
cannot tell which repeat copy they came from, so whether they land on the true copy
is luck. A config is valid on a read set when this accuracy is at most MARGIN below
BWA-MEM2's on the same set (margin fixed before any search run).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MARGIN = 0.0005  # 0.05 percentage points = 100 of 200,000 reads
CONF_MARGIN = 100  # v2: extra confident errors allowed over default RosaSeed (0.05 % of reads)


def unique_accuracy(r: dict) -> float:
    return (r["correct"] - r["mapq0_correct"]) / r["total"]


def confident_wrong(r: dict) -> int:
    """Reads placed with MAPQ > 0 at the wrong position."""
    mapped = round(r["mapped_frac"] * r["total"])
    return mapped - r["correct"] - (r["mapq0"] - r["mapq0_correct"])


def _with_correct(e: dict) -> dict:
    return {**e, "correct": round(e["accuracy"] * e["total"])}


@dataclass(frozen=True)
class Refs:
    default_wall: dict   # read set -> median wall s of default RosaSeed
    bwa_acc: dict        # read set -> BWA-MEM2 unique accuracy
    noise_floor: float   # relative speedup below which differences are noise
    rule: str = "v1"     # v1: accuracy only; v2: accuracy and confident errors
    conf_limit: dict | None = None  # v2: read set -> max confident errors

    def __post_init__(self):
        if self.rule not in ("v1", "v2"):
            raise ValueError(f"unknown validity rule {self.rule!r}")
        if self.rule == "v2" and not self.conf_limit:
            raise ValueError("rule v2 needs conf_limit")

    @classmethod
    def from_calibration(cls, path: Path, rule: str = "v1") -> "Refs":
        if rule not in ("v1", "v2"):
            raise ValueError(f"unknown validity rule {rule!r}")
        c = json.loads(Path(path).read_text())
        return cls(
            default_wall={s: c[f"rs_default_{s}"]["wall_median"] for s in "AB"},
            bwa_acc={s: unique_accuracy(_with_correct(c[f"bwa_{s}"])) for s in "AB"},
            noise_floor=c["speedup_noise_floor"],
            rule=rule,
            conf_limit={s: confident_wrong(_with_correct(c[f"rs_default_{s}"])) + CONF_MARGIN
                        for s in "AB"} if rule == "v2" else None,
        )

    def speedup(self, row: dict, read_set: str) -> float | None:
        if row.get("status") != "ok" or not row.get("wall_s"):
            return None
        return self.default_wall[read_set] / row["wall_s"]

    def valid(self, row: dict, read_set: str) -> bool:
        if row.get("status") != "ok":
            return False
        if unique_accuracy(row) < self.bwa_acc[read_set] - MARGIN - 1e-12:  # float slack
            return False
        if self.rule == "v2" and confident_wrong(row) > self.conf_limit[read_set]:
            return False
        return True
