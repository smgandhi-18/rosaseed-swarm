"""Measure one configuration: run it, score the SAM, delete the SAM."""
from __future__ import annotations

import fcntl
import os
import time
import uuid
from pathlib import Path

from .evaluate import evaluate_sam
from .runner import build_cmd, run_with_retry
from .space import Config


class RunLock:
    """Exclusive lock on a file, so alignments never overlap even when several scripts
    (experiment, analysis, critic probe) run at the same time."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "w")
        fcntl.flock(self._f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._f, fcntl.LOCK_UN)
        self._f.close()


def measure(config: Config | None, read_set: str, cpus: str, cfg: dict, root: Path,
            keep_sam: bool = False) -> dict:
    root = Path(root)
    with RunLock(root / cfg["paths"]["runs_dir"] / "run.lock"):
        return _measure(config, read_set, cpus, cfg, root, keep_sam)


def _measure(config, read_set, cpus, cfg, root, keep_sam) -> dict:
    tag = "bwa" if config is None else config.hash()
    sam = root / cfg["paths"]["runs_dir"] / f"{tag}_{read_set}_{uuid.uuid4().hex[:8]}.sam"
    started = time.time()
    r = run_with_retry(build_cmd(config, read_set, cfg, root), sam, cfg["timeout_s"], cpus)
    out = {
        "status": r.status, "wall_s": r.wall_s, "user_s": r.user_s, "sys_s": r.sys_s,
        "peak_rss_kb": r.peak_rss_kb, "attempts": r.attempts, "threads": cfg["threads"],
        "cpus": cpus, "started": started, "finished": time.time(),
        "binary": "bwa-mem2" if config is None else config.binary_name(),
        "note": None if r.status == "ok" else r.stderr_tail[-300:],
    }
    try:
        if r.status == "ok":
            out.update(evaluate_sam(r.sam_path, cfg["accuracy_tol_bp"]))
    finally:
        for suffix in ([] if keep_sam else [".sam"]) + [".time", ".stderr"]:
            try:
                os.remove(sam.with_suffix(suffix))
            except FileNotFoundError:
                pass
    return out
