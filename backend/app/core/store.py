"""Persist scan results + lifecycle status to SQLite."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..engine.types import Zone

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    direction TEXT NOT NULL,
    ts_ob TEXT NOT NULL,
    ts_bos TEXT,
    low REAL,
    high REAL,
    score INTEGER,
    fresh INTEGER,
    star1 INTEGER,
    star2 INTEGER,
    star3 INTEGER,
    star4 INTEGER,
    star5 INTEGER,
    star5_pending INTEGER,
    entry REAL,
    sl REAL,
    tp1 REAL,
    tp2 REAL,
    rr_tp1 REAL,
    rr_tp2 REAL,
    atr REAL,
    distance_atr REAL,
    last_close REAL,
    session_label TEXT,
    sweep INTEGER,
    trend TEXT,
    fib_eq REAL,
    payload TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    touched_at TEXT,
    touched_session TEXT,
    reacted_at TEXT,
    failed_at TEXT,
    expired_at TEXT,
    outcome TEXT,
    mfe_r REAL DEFAULT 0,
    mae_r REAL DEFAULT 0,
    vanished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_zones_symbol_tf ON zones(symbol, tf);
CREATE INDEX IF NOT EXISTS idx_zones_score ON zones(score);
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    tf TEXT,
    n_symbols INTEGER,
    n_zones INTEGER,
    elapsed_sec REAL,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS notify_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    event TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(zone_id, event)
);
"""

# Payload-only fields computed by the monitor (bias at touch, realistic trade).
PAYLOAD_EXTRA_KEYS = (
    "bias_h4", "bias_d1", "aligned_h4d1", "bias_at",
    "trade_status", "trade_r", "trade_exit", "trade_fill_at", "trade_exit_at",
    "trade_model", "trade_tp", "trade_tp_r", "trade_ref",
)

_EXTRA_COLS = {
    "status": "TEXT DEFAULT 'active'",
    "touched_at": "TEXT",
    "touched_session": "TEXT",
    "reacted_at": "TEXT",
    "failed_at": "TEXT",
    "expired_at": "TEXT",
    "outcome": "TEXT",
    "mfe_r": "REAL DEFAULT 0",
    "mae_r": "REAL DEFAULT 0",
    # Set when an *active* zone is missing from a later scan (e.g. touched inside the
    # last bar → no longer virgin). The row is kept until the lifecycle refresh has
    # checked the candles since its last check (see monitor.refresh_statuses).
    "vanished_at": "TEXT",
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(zones)").fetchall()}
    for name, decl in _EXTRA_COLS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE zones ADD COLUMN {name} {decl}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notify_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id TEXT NOT NULL,
            event TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(zone_id, event)
        )
        """
    )
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(zones)").fetchall()}
    if "status" in cols2:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zones_status ON zones(status)")
    conn.commit()


def replace_zones(
    conn: sqlite3.Connection,
    zones: Iterable[Zone | dict[str, Any]],
    *,
    tf: str | None = None,
    symbols: set[str] | None = None,
) -> int:
    cur = conn.cursor()
    if tf and symbols:
        qmarks = ",".join("?" * len(symbols))
        cur.execute(
            f"DELETE FROM zones WHERE tf=? AND symbol IN ({qmarks})",
            [tf.upper(), *symbols],
        )
    elif tf:
        cur.execute("DELETE FROM zones WHERE tf=?", (tf.upper(),))
    else:
        cur.execute("DELETE FROM zones")

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for z in zones:
        d = z.to_dict() if isinstance(z, Zone) else dict(z)
        rows.append(
            (
                d["id"],
                d["symbol"],
                d["tf"],
                d["direction"],
                d["ts_ob"],
                d.get("ts_bos"),
                d["low"],
                d["high"],
                d["score"],
                int(d.get("fresh", True)),
                int(d.get("star1_fvg", False)),
                int(d.get("star2_trend", False)),
                int(d.get("star3_fib", False)),
                int(d.get("star4_liquidity", False)),
                int(d.get("star5_session", False)),
                int(d.get("star5_pending", False)),
                d["entry"],
                d["sl"],
                d.get("tp1"),
                d.get("tp2"),
                d.get("rr_tp1"),
                d.get("rr_tp2"),
                d.get("atr"),
                d.get("distance_atr"),
                d.get("last_close"),
                d.get("session_label"),
                int(d.get("sweep", False)),
                d.get("trend"),
                d.get("fib_eq"),
                json.dumps(d, default=str),
                now,
                d.get("status", "active"),
                d.get("touched_at"),
                d.get("touched_session"),
                d.get("reacted_at"),
                d.get("failed_at"),
                d.get("expired_at"),
                d.get("outcome"),
                float(d.get("mfe_r") or 0),
                float(d.get("mae_r") or 0),
            )
        )
    cur.executemany(
        """
        INSERT OR REPLACE INTO zones (
            id, symbol, tf, direction, ts_ob, ts_bos, low, high, score, fresh,
            star1, star2, star3, star4, star5, star5_pending,
            entry, sl, tp1, tp2, rr_tp1, rr_tp2, atr, distance_atr, last_close,
            session_label, sweep, trend, fib_eq, payload, scanned_at,
            status, touched_at, touched_session, reacted_at, failed_at, expired_at,
            outcome, mfe_r, mae_r
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)



def upsert_zones(
    conn: sqlite3.Connection,
    zones: Iterable[Zone | dict[str, Any]],
    *,
    tf: str | None = None,
    symbols: set[str] | None = None,
    preserve_lifecycle: bool = True,
) -> int:
    """Insert/update scan zones without wiping lifecycle on known IDs.

    - Preserves status/touched_at/reacted_at/... for existing zone IDs when the
      incoming row is still 'active' (fresh scan does not carry lifecycle).
    - *Active* zones in scope that are absent from this scan are NOT deleted here:
      they are flagged ``vanished_at`` (first time only) and hidden from listings.
      A zone usually vanishes because price touched it inside the last bar (no longer
      virgin) — deleting it before the lifecycle refresh ran lost the first-touch
      alert. ``monitor.refresh_statuses`` then walks the candles: touched → normal
      touchee/reaction/échec flow (alert once, guarded); expired → ``expiree``;
      still untouched/unexpired (dropped for a detection reason, e.g. score) →
      deleted there (see ``delete_zone``).
    - A flagged zone that shows up again in a scan is re-inserted with the flag
      cleared (INSERT OR REPLACE).
    - Zones already progressed (touchee/reaction/echec/expiree) are never touched.
    """
    cur = conn.cursor()
    rows_in: list[dict[str, Any]] = []
    for z in zones:
        d = z.to_dict() if isinstance(z, Zone) else dict(z)
        rows_in.append(d)

    new_ids = {d["id"] for d in rows_in}
    scope_tf = tf.upper() if tf else None

    LIFE_KEYS = (
        "status",
        "touched_at",
        "touched_session",
        "reacted_at",
        "failed_at",
        "expired_at",
        "outcome",
        "mfe_r",
        "mae_r",
    )

    existing: dict[str, dict[str, Any]] = {}
    if preserve_lifecycle and new_ids:
        qmarks = ",".join("?" * len(new_ids))
        for row in cur.execute(
            f"""
            SELECT id, status, touched_at, touched_session, reacted_at, failed_at,
                   expired_at, outcome, mfe_r, mae_r, payload
            FROM zones WHERE id IN ({qmarks})
            """,
            list(new_ids),
        ):
            rec = {k: row[k] for k in ("id", *LIFE_KEYS)}
            try:
                old_payload = json.loads(row["payload"] or "{}")
            except (TypeError, ValueError):
                old_payload = {}
            rec["_payload_extra"] = {
                k: old_payload[k] for k in PAYLOAD_EXTRA_KEYS if k in old_payload
            }
            existing[row["id"]] = rec

    # Flag (never delete) *active* zones in scope that are missing from this scan.
    flag_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if scope_tf:
        clauses = ["tf=?", "(status IS NULL OR status = 'active')", "vanished_at IS NULL"]
        args: list[Any] = [scope_tf]
        if symbols is not None:
            if not symbols:
                clauses.append("0")
            else:
                clauses.append(f"symbol IN ({','.join('?' * len(symbols))})")
                args.extend(symbols)
        if new_ids:
            clauses.append(f"id NOT IN ({','.join('?' * len(new_ids))})")
            args.extend(new_ids)
        cur.execute(
            f"UPDATE zones SET vanished_at=? WHERE {' AND '.join(clauses)}",
            [flag_at, *args],
        )

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for d in rows_in:
        if preserve_lifecycle and d["id"] in existing:
            old = existing[d["id"]]
            old_status = old.get("status") or "active"
            new_status = d.get("status") or "active"
            # Incoming fresh scan has active; keep progressed lifecycle from DB
            if old_status != "active" and new_status == "active":
                for k in LIFE_KEYS:
                    if old.get(k) is not None:
                        d[k] = old[k]
                # bias at touch + realistic trade fields live in the payload only
                for k, v in (old.get("_payload_extra") or {}).items():
                    d.setdefault(k, v)

        rows.append(
            (
                d["id"],
                d["symbol"],
                d["tf"],
                d["direction"],
                d["ts_ob"],
                d.get("ts_bos"),
                d["low"],
                d["high"],
                d["score"],
                int(d.get("fresh", True)),
                int(d.get("star1_fvg", False)),
                int(d.get("star2_trend", False)),
                int(d.get("star3_fib", False)),
                int(d.get("star4_liquidity", False)),
                int(d.get("star5_session", False)),
                int(d.get("star5_pending", False)),
                d["entry"],
                d["sl"],
                d.get("tp1"),
                d.get("tp2"),
                d.get("rr_tp1"),
                d.get("rr_tp2"),
                d.get("atr"),
                d.get("distance_atr"),
                d.get("last_close"),
                d.get("session_label"),
                int(d.get("sweep", False)),
                d.get("trend"),
                d.get("fib_eq"),
                json.dumps(d, default=str),
                now,
                d.get("status", "active"),
                d.get("touched_at"),
                d.get("touched_session"),
                d.get("reacted_at"),
                d.get("failed_at"),
                d.get("expired_at"),
                d.get("outcome"),
                float(d.get("mfe_r") or 0),
                float(d.get("mae_r") or 0),
            )
        )
    cur.executemany(
        """
        INSERT OR REPLACE INTO zones (
            id, symbol, tf, direction, ts_ob, ts_bos, low, high, score, fresh,
            star1, star2, star3, star4, star5, star5_pending,
            entry, sl, tp1, tp2, rr_tp1, rr_tp2, atr, distance_atr, last_close,
            session_label, sweep, trend, fib_eq, payload, scanned_at,
            status, touched_at, touched_session, reacted_at, failed_at, expired_at,
            outcome, mfe_r, mae_r
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def update_zone_lifecycle(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE zones SET
            payload=?,
            status=?,
            touched_at=?,
            touched_session=?,
            reacted_at=?,
            failed_at=?,
            expired_at=?,
            outcome=?,
            mfe_r=?,
            mae_r=?,
            score=?,
            star5=?,
            star5_pending=?,
            session_label=?
        WHERE id=?
        """,
        (
            json.dumps(payload, default=str),
            payload.get("status", "active"),
            payload.get("touched_at"),
            payload.get("touched_session"),
            payload.get("reacted_at"),
            payload.get("failed_at"),
            payload.get("expired_at"),
            payload.get("outcome"),
            float(payload.get("mfe_r") or 0),
            float(payload.get("mae_r") or 0),
            int(payload.get("score") or 0),
            int(bool(payload.get("star5_session"))),
            int(bool(payload.get("star5_pending"))),
            payload.get("session_label"),
            payload["id"],
        ),
    )


def record_run(
    conn: sqlite3.Connection,
    *,
    tf: str,
    n_symbols: int,
    n_zones: int,
    elapsed_sec: float,
    meta: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO scan_runs (started_at, finished_at, tf, n_symbols, n_zones, elapsed_sec, meta)
        VALUES (?,?,?,?,?,?,?)
        """,
        (now, now, tf, n_symbols, n_zones, elapsed_sec, json.dumps(meta or {})),
    )
    conn.commit()


def list_zones(
    conn: sqlite3.Connection,
    *,
    tf: str | None = None,
    group_symbols: set[str] | None = None,
    min_score: int = 4,
    symbol: str | None = None,
    status: str | None = None,
    statuses: list[str] | None = None,
    limit: int = 500,
    active_only_for_scanner: bool = False,
    include_vanished: bool = False,
) -> list[dict[str, Any]]:
    clauses = ["score >= ?"]
    args: list[Any] = [min_score]
    if tf:
        clauses.append("tf = ?")
        args.append(tf.upper())
    if symbol:
        clauses.append("symbol = ?")
        args.append(symbol.upper())
    if group_symbols is not None:
        q = ",".join("?" * len(group_symbols))
        clauses.append(f"symbol IN ({q})")
        args.extend(group_symbols)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if statuses:
        q = ",".join("?" * len(statuses))
        clauses.append(f"status IN ({q})")
        args.extend(statuses)
    if active_only_for_scanner:
        clauses.append("(status IS NULL OR status = 'active')")
    if not include_vanished:
        # Active zones missing from the last scan await the lifecycle check (refresh);
        # hide them like the old delete did. Progressed ones (touchee…) stay visible.
        clauses.append("NOT (vanished_at IS NOT NULL AND (status IS NULL OR status = 'active'))")
    where = " AND ".join(clauses)
    args.append(limit)
    cur = conn.execute(
        f"""
        SELECT payload, status, touched_at, touched_session, reacted_at, failed_at,
               expired_at, outcome, mfe_r, mae_r, vanished_at
        FROM zones
        WHERE {where}
        ORDER BY
            CASE symbol WHEN 'XAUUSD' THEN 0 ELSE 1 END,
            score DESC,
            star3 DESC,
            distance_atr ASC
        LIMIT ?
        """,
        args,
    )
    out = []
    for row in cur:
        d = json.loads(row["payload"])
        # prefer column lifecycle fields when present
        for k in (
            "status",
            "touched_at",
            "touched_session",
            "reacted_at",
            "failed_at",
            "expired_at",
            "outcome",
            "mfe_r",
            "mae_r",
        ):
            if row[k] is not None:
                d[k] = row[k]
        if "status" not in d:
            d["status"] = "active"
        if row["vanished_at"] is not None:
            d["vanished_at"] = row["vanished_at"]
        else:
            d.pop("vanished_at", None)
        out.append(d)
    return out


def delete_zone(conn: sqlite3.Connection, zone_id: str) -> int:
    """Delete one zone row (refresh: vanished from the scan, never touched/expired)."""
    cur = conn.execute("DELETE FROM zones WHERE id=?", (zone_id,))
    return int(cur.rowcount or 0)


def count_by_status(conn: sqlite3.Connection, *, tf: str | None = None) -> dict[str, int]:
    args: list[Any] = []
    where = ""
    if tf:
        where = "WHERE tf=?"
        args.append(tf.upper())
    cur = conn.execute(
        f"SELECT COALESCE(status,'active') AS st, COUNT(*) AS n FROM zones {where} GROUP BY st",
        args,
    )
    return {r["st"]: r["n"] for r in cur}


def was_notified(conn: sqlite3.Connection, zone_id: str, event: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM notify_log WHERE zone_id=? AND event=?",
        (zone_id, event),
    ).fetchone()
    return row is not None


def mark_notified(conn: sqlite3.Connection, zone_id: str, event: str) -> None:
    """Idempotent insert (legacy). Prefer claim_notify for send-path dedupe."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO notify_log (zone_id, event, created_at) VALUES (?,?,?)",
            (zone_id, event, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def claim_notify(conn: sqlite3.Connection, zone_id: str, event: str) -> bool:
    """Atomically claim a (zone_id, event) notify slot before sending.

    Returns True if this caller won the claim (should send). False if already
    claimed — skips duplicate Telegram sends under concurrent refresh/pipeline.
    Uses INSERT OR IGNORE + UNIQUE(zone_id, event); BEGIN IMMEDIATE for writer lock.
    """
    if not zone_id or not event:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT OR IGNORE INTO notify_log (zone_id, event, created_at) VALUES (?,?,?)",
            (zone_id, event, now),
        )
        conn.commit()
        return cur.rowcount == 1
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        # Fail closed: skip send rather than risk a duplicate Telegram.
        return False


def dump_json(path: Path, zones: Iterable[Any], meta: dict[str, Any] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for z in zones:
        items.append(z.to_dict() if isinstance(z, Zone) else dict(z))
    payload = {"meta": meta or {}, "zones": items}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
