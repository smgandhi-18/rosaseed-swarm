"""Run queue: a fixed number of worker slots, each pinned to its own CPU die.

Agents may propose in parallel, but at most `n_workers` alignments run at once and
each one owns a whole die, so runtimes are comparable across conditions.
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from .measure import measure
from .space import Config

METRIC_KEYS = ("status", "wall_s", "user_s", "sys_s", "peak_rss_kb", "accuracy", "mapped_frac",
               "correct", "total", "wrong_q30", "mapq0", "mapq0_correct", "threads", "cpus",
               "binary", "started", "finished")


class RunQueue:
    def __init__(self, cfg: dict, root: Path, store, measure_fn=measure):
        self.cfg, self.root, self.store = cfg, Path(root), store
        self._measure = measure_fn
        self._slots: queue.Queue[str] = queue.Queue()
        for cpus in cfg["cpus"]["workers"][: cfg["n_workers"]]:
            self._slots.put(cpus)
        self._cache_lock = threading.Lock()
        self._inflight: dict[tuple[str, str], threading.Event] = {}

    def run(self, config: Config, read_set: str, meta: dict, use_cache: bool = True) -> dict:
        """Run (or reuse) one configuration and log it. Blocks until a slot is free.

        meta: condition, repeat, proposer, purpose. Returns the stored row.
        """
        key = (config.hash(), read_set, meta["condition"], meta["repeat"])
        if use_cache:
            with self._cache_lock:
                hit = self.store.cached(*key)
                wait = self._inflight.get(key) if hit is None else None
                if hit is None and wait is None:
                    self._inflight[key] = threading.Event()
            if wait is not None:          # same config already running for someone else
                wait.wait()
                hit = self.store.cached(*key)
            if hit is not None:
                row = {k: hit[k] for k in METRIC_KEYS}
                row.update(cached_from=hit["id"], attempts=0, note=hit.get("note"))
                return self._log(config, read_set, meta, row)
        cpus = self._slots.get()
        try:
            m = self._measure(config, read_set, cpus, self.cfg, self.root)
        except Exception as e:  # never leave waiters blocked; log the failure as a crash
            m = {"status": "crash", "note": f"harness error: {e!r}", "cpus": cpus}
        finally:
            self._slots.put(cpus)
        try:
            row = {k: m.get(k) for k in METRIC_KEYS + ("attempts", "note")}
            return self._log(config, read_set, meta, row)
        finally:
            if use_cache:
                with self._cache_lock:
                    ev = self._inflight.pop(key, None)
                if ev:
                    ev.set()

    def _log(self, config: Config, read_set: str, meta: dict, row: dict) -> dict:
        full = {**row, **{k: meta[k] for k in ("condition", "repeat", "proposer", "purpose")},
                "read_set": read_set, "config_json": json.dumps(config.to_dict(), sort_keys=True),
                "config_hash": config.hash()}
        full["id"] = self.store.add_run(full)
        return full
