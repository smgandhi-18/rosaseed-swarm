import fcntl
import json
import os
import threading
import time

from swarm.measure import RunLock
from tests.test_tools import box, run  # noqa: F401  (fixture reuse)


def test_tool_errors_never_escape(box):
    out = json.loads(box.call("read_log", {"top": "all"}))
    assert "error" in out


def test_run_lock_is_exclusive_across_holders(tmp_path):
    path = tmp_path / "run.lock"
    order = []

    def hold(tag, delay):
        with RunLock(path):
            order.append(f"{tag}-in")
            time.sleep(delay)
            order.append(f"{tag}-out")

    t = threading.Thread(target=hold, args=("a", 0.3))
    t.start()
    time.sleep(0.05)
    hold("b", 0)
    t.join()
    assert order == ["a-in", "a-out", "b-in", "b-out"]
