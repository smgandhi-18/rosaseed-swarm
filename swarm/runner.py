"""Run one alignment under GNU time, pinned to a CPU set, with a timeout and one retry."""
from __future__ import annotations

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .space import Config


@dataclass
class RunResult:
    status: str                 # "ok", "timeout" or "crash"
    wall_s: float | None = None
    user_s: float | None = None
    sys_s: float | None = None
    peak_rss_kb: int | None = None
    sam_path: str | None = None
    stderr_tail: str = ""
    attempts: int = 1


def _clock_to_s(text: str) -> float:
    parts = [float(p) for p in text.strip().split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def parse_time_v(text: str) -> dict:
    out = {}
    pats = {
        "user_s": (r"User time \(seconds\): ([\d.]+)", float),
        "sys_s": (r"System time \(seconds\): ([\d.]+)", float),
        "wall_s": (r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)", _clock_to_s),
        "peak_rss_kb": (r"Maximum resident set size \(kbytes\): (\d+)", int),
    }
    for key, (pat, conv) in pats.items():
        m = re.search(pat, text)
        if m:
            out[key] = conv(m.group(1))
    return out


def build_cmd(config: Config | None, read_set: str, cfg: dict, root: Path) -> list[str]:
    """Alignment command for a RosaSeed config, or stock BWA-MEM2 when config is None."""
    p = cfg["paths"]
    r1, r2 = (str(root / f) for f in p["reads"][read_set])
    bwa_index = str(root / p["bwa_index"])
    threads = str(cfg["threads"])
    if config is None:
        return [str(root / p["bin_dir"] / "bwa-mem2"), "mem", "-t", threads, bwa_index, r1, r2]
    return [str(root / p["bin_dir"] / config.binary_name()), "mem", "-t", threads,
            *config.argv(), "--rs-index", str(root / p["rs_index"]), bwa_index, r1, r2]


def run_once(cmd: list[str], out_sam: Path, timeout_s: float, cpus: str | None = None) -> RunResult:
    out_sam = Path(out_sam)
    out_sam.parent.mkdir(parents=True, exist_ok=True)
    time_log = out_sam.with_suffix(".time")
    err_log = out_sam.with_suffix(".stderr")
    full = ["/usr/bin/time", "-v", "-o", str(time_log), *cmd]
    if cpus is not None:
        full = ["taskset", "-c", cpus, "nice", "-n", "19", *full]
    with open(out_sam, "w") as fo, open(err_log, "w") as fe:
        proc = subprocess.Popen(full, stdout=fo, stderr=fe, start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return RunResult("timeout", stderr_tail=_tail(err_log))
    times = parse_time_v(time_log.read_text()) if time_log.exists() else {}
    if rc != 0:
        return RunResult("crash", stderr_tail=_tail(err_log), **times)
    return RunResult("ok", sam_path=str(out_sam), stderr_tail=_tail(err_log), **times)


def run_with_retry(cmd: list[str], out_sam: Path, timeout_s: float, cpus: str | None = None) -> RunResult:
    """Retry once after a crash. A timeout is not retried: it would just time out again."""
    r = run_once(cmd, out_sam, timeout_s, cpus)
    if r.status == "crash":
        r = run_once(cmd, out_sam, timeout_s, cpus)
        r.attempts = 2
    return r


def _tail(path: Path, n: int = 800) -> str:
    try:
        return Path(path).read_text(errors="replace")[-n:]
    except FileNotFoundError:
        return ""
