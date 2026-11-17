"""Score a SAM file of wgsim reads against the true positions in the read names.

wgsim names a pair `<chrom>_<start>_<end>_<err1>_<err2>_<id>`, where start and end are
the 1-based ends of the simulated fragment. A forward-strand read starts at `start`;
a reverse-strand read ends at `end`. A read is correct when its primary alignment is
on the right chromosome and its unclipped start (forward) or unclipped end (reverse)
is within `tol` bp of the truth.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

_NAME = re.compile(r"^(.+)_(\d+)_(\d+)_\d+:\d+:\d+_\d+:\d+:\d+_[0-9a-f]+$")
_CIGAR = re.compile(r"(\d+)([MIDNSHP=X])")

FLAG_UNMAPPED = 0x4
FLAG_REVERSE = 0x10
FLAG_SECONDARY = 0x100
FLAG_SUPPLEMENTARY = 0x800


def parse_truth(qname: str) -> tuple[str, int, int]:
    m = _NAME.match(qname)
    if not m:
        raise ValueError(f"not a wgsim read name: {qname!r}")
    return m.group(1), int(m.group(2)), int(m.group(3))


def _unclipped_bounds(pos: int, cigar: str) -> tuple[int, int]:
    ops = _CIGAR.findall(cigar)
    lead = 0
    for n, op in ops:
        if op not in "SH":
            break
        lead += int(n)
    trail = 0
    for n, op in reversed(ops):
        if op not in "SH":
            break
        trail += int(n)
    ref_len = sum(int(n) for n, op in ops if op in "MDN=X")
    return pos - lead, pos + ref_len - 1 + trail


def evaluate_sam(path, tol: int = 20) -> dict:
    total = mapped = correct = wrong_q30 = mapq0 = mapq0_correct = 0
    with open(Path(path)) as f:
        for line in f:
            if line.startswith("@"):
                continue
            q, flag, rname, pos, mapq, cigar = line.split("\t", 6)[:6]
            flag = int(flag)
            if flag & (FLAG_SECONDARY | FLAG_SUPPLEMENTARY):
                continue
            total += 1
            if flag & FLAG_UNMAPPED:
                continue
            mapped += 1
            chrom, t_start, t_end = parse_truth(q)
            start, end = _unclipped_bounds(int(pos), cigar)
            if rname != chrom:
                ok = False
            elif flag & FLAG_REVERSE:
                ok = abs(end - t_end) <= tol
            else:
                ok = abs(start - t_start) <= tol
            correct += ok
            mapq = int(mapq)
            if mapq == 0:
                mapq0 += 1
                mapq0_correct += ok
            elif mapq >= 30 and not ok:
                wrong_q30 += 1
    return {
        "total": total,
        "mapped": mapped,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "mapped_frac": mapped / total if total else 0.0,
        "wrong_q30": wrong_q30,
        "mapq0": mapq0,
        "mapq0_correct": mapq0_correct,
    }


def placement_noise(r: dict) -> float:
    """Standard deviation of accuracy caused by placing MAPQ-0 (multi-mapping) reads.

    Each MAPQ-0 read lands on one of several equally good copies, so whether it is
    counted correct is close to a coin flip with p = mapq0_correct / mapq0. Two
    configurations can differ in accuracy by about this much for no real reason.
    """
    n = r["mapq0"]
    if not n or not r["total"]:
        return 0.0
    p = r["mapq0_correct"] / n
    return math.sqrt(n * p * (1 - p)) / r["total"]
