"""SQLite state for the Aérogest watcher (tables prefixed aerogest_, in the shared DB)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from .parse import Slot

SCHEMA = """
CREATE TABLE IF NOT EXISTS aerogest_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS aerogest_free (
  reg TEXT NOT NULL, day TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
  PRIMARY KEY (reg, day, start));
CREATE TABLE IF NOT EXISTS aerogest_days (reg TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (reg, day));
CREATE TABLE IF NOT EXISTS aerogest_alerts (
  reg TEXT NOT NULL, day TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
  sent_at TEXT NOT NULL, PRIMARY KEY (reg, day, start, end));
CREATE TABLE IF NOT EXISTS aerogest_runs (
  ts TEXT NOT NULL, ok INTEGER, b23 TEXT, horizon TEXT, free_count INTEGER,
  new_count INTEGER, sent INTEGER, error TEXT);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn, key: str) -> str | None:
    r = conn.execute("SELECT value FROM aerogest_meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO aerogest_meta(key,value) VALUES(?,?)", (key, value))
    conn.commit()


def _overlap(a0, a1, b0, b1) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def newly_freed(prev: list[tuple[int, int]], slot: Slot) -> int:
    """Minutes of `slot` that were NOT free at the previous check."""
    return slot.minutes - sum(_overlap(slot.start, slot.end, s, e) for s, e in prev)


def apply_snapshot(conn, reg: str, days: dict[date, list[Slot]], min_new: int = 30,
                   today: date | None = None) -> list[Slot]:
    """Store the new snapshot for `reg` and return slots to alert on.

    Alert only when a slot contains >= min_new minutes that were not free before (e.g. a
    cancellation) on a day that was already tracked. Days seen for the first time (first
    run, horizon moving forward) are recorded silently. Each exact slot is alerted once.
    """
    known = {r[0] for r in conn.execute("SELECT day FROM aerogest_days WHERE reg=?", (reg,))}
    out: list[Slot] = []
    for day, slots in sorted(days.items()):
        d = day.isoformat()
        if d in known:
            prev = [(r[0], r[1]) for r in conn.execute(
                "SELECT start,end FROM aerogest_free WHERE reg=? AND day=?", (reg, d))]
            for s in slots:
                if newly_freed(prev, s) >= min_new and not conn.execute(
                        "SELECT 1 FROM aerogest_alerts WHERE reg=? AND day=? AND start=? AND end=?",
                        (reg, d, s.start, s.end)).fetchone():
                    out.append(s)
        conn.execute("DELETE FROM aerogest_free WHERE reg=? AND day=?", (reg, d))
        conn.executemany("INSERT OR REPLACE INTO aerogest_free(reg,day,start,end) VALUES(?,?,?,?)",
                         [(reg, d, s.start, s.end) for s in slots])
        conn.execute("INSERT OR IGNORE INTO aerogest_days(reg,day) VALUES(?,?)", (reg, d))
    if today is not None:
        for t in ("aerogest_free", "aerogest_days"):
            conn.execute(f"DELETE FROM {t} WHERE day < ?", (today.isoformat(),))
    conn.commit()
    return out


def mark_alerted(conn, s: Slot) -> None:
    conn.execute("INSERT OR IGNORE INTO aerogest_alerts(reg,day,start,end,sent_at) VALUES(?,?,?,?,?)",
                 (s.reg, s.day.isoformat(), s.start, s.end, datetime.utcnow().isoformat(timespec="seconds")))
    conn.commit()


def log_run(conn, **kw) -> None:
    conn.execute("INSERT INTO aerogest_runs(ts,ok,b23,horizon,free_count,new_count,sent,error) VALUES(?,?,?,?,?,?,?,?)",
                 (datetime.utcnow().isoformat(timespec="seconds"), kw.get("ok"), kw.get("b23"), kw.get("horizon"),
                  kw.get("free_count"), kw.get("new_count"), kw.get("sent"), kw.get("error")))
    conn.execute("DELETE FROM aerogest_runs WHERE rowid NOT IN (SELECT rowid FROM aerogest_runs ORDER BY rowid DESC LIMIT 500)")
    conn.commit()
