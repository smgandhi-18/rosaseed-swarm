"""SQLite results store shared by every agent and condition (one row per run)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

RUN_COLUMNS = [
    "condition", "repeat", "proposer", "read_set", "purpose", "config_json", "config_hash",
    "binary", "status", "wall_s", "user_s", "sys_s", "peak_rss_kb", "accuracy",
    "mapped_frac", "correct", "total", "wrong_q30", "mapq0", "mapq0_correct", "threads", "cpus", "cached_from", "attempts",
    "started", "finished", "note",
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, {", ".join(RUN_COLUMNS)});
CREATE TABLE IF NOT EXISTS llm_calls (id INTEGER PRIMARY KEY, condition, repeat, agent,
    prompt_tokens, completion_tokens, seconds, ts);
CREATE TABLE IF NOT EXISTS claims (id INTEGER PRIMARY KEY, condition, repeat, agent,
    config_json, claimed_json, text, verdict, reason, ts);
CREATE TABLE IF NOT EXISTS done (condition, repeat, wall_s, ts, PRIMARY KEY (condition, repeat));
"""


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def _insert(self, table: str, row: dict) -> int:
        cols = list(row)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self._lock:
            cur = self._db.execute(sql, [row[c] for c in cols])
            self._db.commit()
            return cur.lastrowid

    def add_run(self, row: dict) -> int:
        unknown = set(row) - set(RUN_COLUMNS)
        if unknown:
            raise ValueError(f"unknown run columns: {sorted(unknown)}")
        return self._insert("runs", row)

    def runs(self, **filters) -> list[dict]:
        where = " AND ".join(f"{k} = ?" for k in filters) or "1"
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM runs WHERE {where} ORDER BY id",
                                    list(filters.values())).fetchall()
        return [dict(r) for r in rows]

    def cached(self, config_hash: str, read_set: str, condition, repeat) -> dict | None:
        """Most recent real (not itself cached) successful search run of this config on this
        set within the same condition and repeat. Conditions never share runs, so each
        condition's wall time is its own."""
        with self._lock:
            r = self._db.execute(
                "SELECT * FROM runs WHERE config_hash = ? AND read_set = ? AND status = 'ok' "
                "AND cached_from IS NULL AND purpose = 'search' AND condition = ? AND repeat = ? "
                "ORDER BY id DESC LIMIT 1",
                (config_hash, read_set, condition, repeat)).fetchone()
        return dict(r) if r else None

    def add_llm_call(self, condition, repeat, agent, prompt_tokens, completion_tokens, seconds):
        self._insert("llm_calls", {"condition": condition, "repeat": repeat, "agent": agent,
                                   "prompt_tokens": prompt_tokens,
                                   "completion_tokens": completion_tokens,
                                   "seconds": seconds, "ts": time.time()})

    def llm_totals(self, condition, repeat) -> dict:
        with self._lock:
            r = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), "
                "COALESCE(SUM(completion_tokens),0), COALESCE(SUM(seconds),0) "
                "FROM llm_calls WHERE condition = ? AND repeat = ?", (condition, repeat)).fetchone()
        return {"calls": r[0], "prompt_tokens": r[1], "completion_tokens": r[2], "seconds": r[3]}

    def add_claim(self, row: dict) -> int:
        return self._insert("claims", {**row, "ts": time.time()})

    def claims(self, **filters) -> list[dict]:
        where = " AND ".join(f"{k} = ?" for k in filters) or "1"
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM claims WHERE {where} ORDER BY id",
                                    list(filters.values())).fetchall()
        return [dict(r) for r in rows]

    def set_claim_verdict(self, claim_id: int, verdict: str, reason: str):
        with self._lock:
            self._db.execute("UPDATE claims SET verdict = ?, reason = ? WHERE id = ?",
                             (verdict, reason, claim_id))
            self._db.commit()

    def mark_done(self, condition, repeat, wall_s: float | None = None):
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO done VALUES (?, ?, ?, ?)",
                             (condition, repeat, wall_s, time.time()))
            self._db.commit()

    def is_done(self, condition, repeat) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM done WHERE condition = ? AND repeat = ?",
                                    (condition, repeat)).fetchone() is not None

    def delete_partial(self, condition, repeat):
        """Remove every row of an interrupted (condition, repeat) so it can be rerun cleanly."""
        with self._lock:
            for table in ("runs", "llm_calls", "claims"):
                self._db.execute(f"DELETE FROM {table} WHERE condition = ? AND repeat = ?",
                                 (condition, repeat))
            self._db.commit()

    def done_list(self) -> list[tuple[str, int]]:
        with self._lock:
            return [(r[0], r[1]) for r in
                    self._db.execute("SELECT condition, repeat FROM done ORDER BY repeat, ts")]

    def done_row(self, condition, repeat) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM done WHERE condition = ? AND repeat = ?",
                                 (condition, repeat)).fetchone()
        return dict(r) if r else None
