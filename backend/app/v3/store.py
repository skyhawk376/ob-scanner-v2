"""SQLite persistence for v3 (own tables in the same zones.sqlite; v2 tables untouched)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS v3_zones (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    grp TEXT,
    tf TEXT NOT NULL,
    direction TEXT NOT NULL,
    ts_ob TEXT NOT NULL,
    state TEXT NOT NULL,
    score INTEGER,
    def TEXT NOT NULL,
    result TEXT NOT NULL,
    entry_ts TEXT,
    exit_ts TEXT,
    exit TEXT,
    r_net REAL,
    first_seen TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_v3_state ON v3_zones(state);
CREATE INDEX IF NOT EXISTS idx_v3_sym_tf ON v3_zones(symbol, tf);
CREATE TABLE IF NOT EXISTS v3_notify (
    zone_id TEXT NOT NULL,
    event TEXT NOT NULL,
    event_ts TEXT,
    status TEXT NOT NULL,
    text TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(zone_id, event)
);
CREATE TABLE IF NOT EXISTS v3_meta (k TEXT PRIMARY KEY, v TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    conn.executescript(SCHEMA)
    return conn


def meta_get(conn, k: str) -> str | None:
    r = conn.execute("SELECT v FROM v3_meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else None


def meta_set(conn, k: str, v: str) -> None:
    conn.execute("INSERT INTO v3_meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    conn.commit()


def upsert_zone(conn, zdef: dict[str, Any], res: dict[str, Any]) -> None:
    tr = res.get("trade") or {}
    conn.execute(
        """INSERT INTO v3_zones(id,symbol,grp,tf,direction,ts_ob,state,score,def,result,entry_ts,exit_ts,exit,r_net,first_seen,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET state=excluded.state, score=excluded.score, result=excluded.result,
             entry_ts=excluded.entry_ts, exit_ts=excluded.exit_ts, exit=excluded.exit, r_net=excluded.r_net,
             updated_at=excluded.updated_at""",
        (zdef["id"], zdef["symbol"], zdef.get("group"), zdef["tf"], zdef["direction"], zdef["ts_ob"],
         res["state"], int(res.get("score") or 0), json.dumps(zdef), json.dumps(res, default=str),
         tr.get("entry_ts"), tr.get("exit_ts"), tr.get("exit"), tr.get("r_net"), now_iso(), now_iso()),
    )


def stored_zones(conn, *, symbol: str | None = None, tf: str | None = None,
                 states: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM v3_zones WHERE 1=1"
    args: list[Any] = []
    if symbol:
        q += " AND symbol=?"
        args.append(symbol)
    if tf:
        q += " AND tf=?"
        args.append(tf)
    if states:
        q += f" AND state IN ({','.join('?' * len(states))})"
        args.extend(states)
    return conn.execute(q, args).fetchall()


def claim(conn, zone_id: str, event: str, event_ts: str | None, status: str, text: str | None = None) -> bool:
    """Atomic one-message-per-(zone, event). False = already claimed (duplicate)."""
    try:
        conn.execute(
            "INSERT INTO v3_notify(zone_id,event,event_ts,status,text,created_at) VALUES(?,?,?,?,?,?)",
            (zone_id, event, event_ts, status, text, now_iso()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def set_notify_status(conn, zone_id: str, event: str, status: str, text: str | None = None) -> None:
    conn.execute("UPDATE v3_notify SET status=?, text=COALESCE(?, text) WHERE zone_id=? AND event=?",
                 (status, text, zone_id, event))
    conn.commit()


def notify_status(conn, zone_id: str, event: str) -> str | None:
    r = conn.execute("SELECT status FROM v3_notify WHERE zone_id=? AND event=?", (zone_id, event)).fetchone()
    return r["status"] if r else None
