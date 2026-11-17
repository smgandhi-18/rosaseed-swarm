"""The RosaSeed configuration space searched by every condition.

A configuration picks one of 20 prebuilt binaries (compile-time flags) plus four
runtime options. Agents send configurations as JSON dicts; `validate` turns them into
a frozen `Config` or raises ValueError with a message the agent can act on.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass

# Compile-time axes (one prebuilt binary per combination).
PRECHAIN = ["off", "t50w60", "t50w80", "t200w60", "t200w80"]
BOOLS = [True, False]

# Runtime axes.
K_RANGE = (15, 25)
CAP_VALUES = [50, 100, 200, 500, 1000, 2000, 5000]
GAP_RANGE = (1, 15)
GAP_STEP_RANGE = (1, 10)

FIELDS = ["prechain", "frc", "early_exit", "k", "cap", "gap", "gap_step"]


@dataclass(frozen=True)
class Config:
    prechain: str      # pre-chain singleton filter: off or t<trigger>w<weak_len>
    frc: bool          # ENABLE_F_RC_CHOICE (strand choice at the first pivot)
    early_exit: bool   # GAPFILL_EARLY_EXIT (Phase C stops at the first good seed)
    k: int             # -k, minimum seed length
    cap: int           # --rs-cap, Phase A SA interval cap
    gap: int           # --rs-gap, Phase C gap threshold
    gap_step: int      # --rs-gap-step, Phase C left step

    def to_dict(self) -> dict:
        return asdict(self)

    def hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha1(blob).hexdigest()[:12]

    def binary_name(self) -> str:
        return f"rs_{self.prechain}_frc{int(self.frc)}_ee{int(self.early_exit)}"

    def argv(self) -> list[str]:
        return ["-k", str(self.k), "--rs-cap", str(self.cap),
                "--rs-gap", str(self.gap), "--rs-gap-step", str(self.gap_step)]


DEFAULT = Config("t200w60", True, True, 19, 2000, 5, 4)


def _as_int(name: str, v) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{name} must be an integer, got {v!r}")
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        v = int(v)
    if not isinstance(v, int):
        raise ValueError(f"{name} must be an integer, got {v!r}")
    return v


def _as_bool(name: str, v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    raise ValueError(f"{name} must be true or false, got {v!r}")


def _in_range(name: str, v: int, lo: int, hi: int) -> int:
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {v}")
    return v


def validate(d: dict) -> Config:
    if not isinstance(d, dict):
        raise ValueError(f"config must be a JSON object with fields {FIELDS}")
    missing = [f for f in FIELDS if f not in d]
    unknown = [f for f in d if f not in FIELDS]
    if missing:
        raise ValueError(f"missing fields: {missing}; required: {FIELDS}")
    if unknown:
        raise ValueError(f"unknown fields: {unknown}; allowed: {FIELDS}")
    if d["prechain"] not in PRECHAIN:
        raise ValueError(f"prechain must be one of {PRECHAIN}, got {d['prechain']!r}")
    cap = _as_int("cap", d["cap"])
    if cap not in CAP_VALUES:
        raise ValueError(f"cap must be one of {CAP_VALUES}, got {cap}")
    return Config(
        prechain=d["prechain"],
        frc=_as_bool("frc", d["frc"]),
        early_exit=_as_bool("early_exit", d["early_exit"]),
        k=_in_range("k", _as_int("k", d["k"]), *K_RANGE),
        cap=cap,
        gap=_in_range("gap", _as_int("gap", d["gap"]), *GAP_RANGE),
        gap_step=_in_range("gap_step", _as_int("gap_step", d["gap_step"]), *GAP_STEP_RANGE),
    )


def random_config(rng: random.Random) -> Config:
    return Config(
        prechain=rng.choice(PRECHAIN),
        frc=rng.choice(BOOLS),
        early_exit=rng.choice(BOOLS),
        k=rng.randint(*K_RANGE),
        cap=rng.choice(CAP_VALUES),
        gap=rng.randint(*GAP_RANGE),
        gap_step=rng.randint(*GAP_STEP_RANGE),
    )


def all_binary_names() -> list[str]:
    return [Config(p, f, e, DEFAULT.k, DEFAULT.cap, DEFAULT.gap, DEFAULT.gap_step).binary_name()
            for p in PRECHAIN for f in BOOLS for e in BOOLS]


def describe_space() -> str:
    return (
        "A RosaSeed configuration is a JSON object with exactly these fields:\n"
        f"- prechain: one of {PRECHAIN}. Pre-chain singleton filter: 'off', or "
        "t<T>w<W> = once a read already has more than T chains, a seed shorter than W nt "
        "may not start a new singleton chain (less extension work, may lose alignments).\n"
        "- frc: true/false. At the first pivot, look up both strands and keep the more "
        "specific one (one extra lookup per read).\n"
        "- early_exit: true/false. Phase C gap filling stops at the first good seed in a "
        "gap instead of trying every pivot.\n"
        f"- k: integer {K_RANGE[0]}..{K_RANGE[1]}. Minimum seed length (Phase C uses k+1). "
        "Larger = fewer, more specific seeds; faster but may miss alignments.\n"
        f"- cap: one of {CAP_VALUES}. Phase A skips seeds occurring more than cap times. "
        "Lower = faster, may miss seeds in repeats.\n"
        f"- gap: integer {GAP_RANGE[0]}..{GAP_RANGE[1]}. Minimum uncovered read stretch "
        "that triggers a Phase C search.\n"
        f"- gap_step: integer {GAP_STEP_RANGE[0]}..{GAP_STEP_RANGE[1]}. Step between "
        "Phase C pivot positions inside a gap.\n"
    )
