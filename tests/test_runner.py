import os
import stat
from pathlib import Path

import pytest

from swarm.runner import parse_time_v, run_once, run_with_retry

# The runner measures every alignment with GNU time; these tests need it installed.
needs_gnu_time = pytest.mark.skipif(not os.access("/usr/bin/time", os.X_OK),
                                    reason="GNU time (/usr/bin/time) is not installed")

TIME_V = """\tCommand being timed: "x"
\tUser time (seconds): 10.25
\tSystem time (seconds): 0.50
\tElapsed (wall clock) time (h:mm:ss or m:ss): 1:02.50
\tMaximum resident set size (kbytes): 123456
\tExit status: 0
"""


def _script(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake.sh"
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_parse_time_v():
    t = parse_time_v(TIME_V)
    assert t == {"wall_s": 62.5, "user_s": 10.25, "sys_s": 0.5, "peak_rss_kb": 123456}
    assert parse_time_v("Elapsed (wall clock) time (h:mm:ss or m:ss): 1:00:01")["wall_s"] == 3601


@needs_gnu_time
def test_ok_run_writes_sam(tmp_path):
    cmd = [_script(tmp_path, "echo '@HD'; echo noise >&2")]
    r = run_once(cmd, tmp_path / "out.sam", timeout_s=10)
    assert r.status == "ok"
    assert (tmp_path / "out.sam").read_text() == "@HD\n"
    assert r.wall_s >= 0 and r.peak_rss_kb > 0


@needs_gnu_time
def test_timeout_kills(tmp_path):
    cmd = [_script(tmp_path, "sleep 30")]
    r = run_once(cmd, tmp_path / "out.sam", timeout_s=1)
    assert r.status == "timeout"


@needs_gnu_time
def test_retry_once_after_crash(tmp_path):
    flag = tmp_path / "failed_once"
    cmd = [_script(tmp_path, f'if [ ! -e {flag} ]; then touch {flag}; exit 3; fi; echo ok')]
    r = run_with_retry(cmd, tmp_path / "out.sam", timeout_s=10)
    assert r.status == "ok" and r.attempts == 2


@needs_gnu_time
def test_two_crashes_is_crash(tmp_path):
    cmd = [_script(tmp_path, "echo boom >&2; exit 3")]
    r = run_with_retry(cmd, tmp_path / "out.sam", timeout_s=10)
    assert r.status == "crash" and r.attempts == 2
    assert "boom" in r.stderr_tail


@needs_gnu_time
def test_timeout_is_not_retried(tmp_path):
    cmd = [_script(tmp_path, "sleep 30")]
    r = run_with_retry(cmd, tmp_path / "out.sam", timeout_s=1)
    assert r.status == "timeout" and r.attempts == 1
