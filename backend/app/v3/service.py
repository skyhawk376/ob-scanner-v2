"""v3 live layer: per-TF refresh (detect → simulate → persist → alert), open-trade
tracking every tick, API/MCP views and stats."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..core.cache import read_cache
from ..core.config import Settings, get_settings
from ..core.symbols import Instrument, load_instruments
from . import params as P
from . import store as S
from .alerts import format_event, max_age_sec
from .detect import detect_zones
from .sim import TERMINAL, norm_index, simulate_zone

LIVE_STATES = ("active", "touched", "waiting", "entered", "be")
TRADE_STATES = ("touched", "entered", "be")
KIND_ORDER = {"touch": 0, "entry": 1, "be": 2, "exit": 3}
UI_STATUS = {"active": "active", "touched": "touchee", "waiting": "touchee", "entered": "en_position",
             "be": "en_position", "tp": "tp", "sl": "sl", "be_exit": "be", "invalidated": "invalidee",
             "expired": "expiree"}


def _utcnow() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").floor("s")


def universe(settings: Settings | None = None) -> list[Instrument]:
    """v3 instruments: V3_GROUPS (METAUX, FOREX, CRYPTO, NQ100). NQ100 = the index only
    (NAS100 via Yahoo NQ=F) unless V3_NQ100_STOCKS=true."""
    settings = settings or get_settings()
    groups = settings.v3_group_list
    out = []
    for i in load_instruments(settings.symbols_yaml):
        if i.group not in groups:
            continue
        if i.group == "NQ100" and i.id != "NAS100" and not settings.v3_nq100_stocks:
            continue
        out.append(i)
    return out


def _fresh_enough(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> bool:
    if df is None or df.empty:
        return False
    step = pd.Timedelta(minutes=P.TF_MIN[tf])
    return df.index[-1] >= now - 2 * step


def _fetch(inst: Instrument, tf: str, settings: Settings, limit: int) -> bool:
    if not settings.enable_fetch:
        return False
    try:
        from ..core.fetcher import fetch_instrument_tf
        from ..providers.registry import ProviderHub

        r = fetch_instrument_tf(ProviderHub(settings), inst, tf, settings=settings, limit=limit)
        return bool(r.ok)
    except Exception as e:  # pragma: no cover
        print(f"[v3] ltf fetch {inst.id} {tf} failed: {e}", flush=True)
        return False


def _armed_ts(conn, tf: str) -> float | None:
    v = S.meta_get(conn, f"armed_{tf}")
    return float(v) if v else None


class _Ctx:
    def __init__(self, settings: Settings, now: pd.Timestamp, notify: bool, fetch_ltf: bool):
        self.settings = settings
        self.now = now
        self.notify = notify
        self.fetch_ltf = fetch_ltf
        self.touch_budget = P.MAX_TOUCH_ALERTS_PER_CYCLE
        self.sent: list[dict] = []
        self.skipped: dict[str, int] = {}
        self.fetched: set[tuple[str, str]] = set()


def _emit(conn, ctx: _Ctx, zdef: dict, res: dict, armed: float | None) -> None:
    settings = ctx.settings
    tf = zdef["tf"]
    evs = sorted(res.get("events") or [], key=lambda e: (e["ts"], KIND_ORDER[e["kind"]]))
    for ev in evs:
        key = ev["key"]
        if S.notify_status(conn, zdef["id"], key):
            continue
        ets = pd.Timestamp(ev["ts"])
        reason = None
        if not ctx.notify:
            reason = "skipped_warmup"
        elif armed is None or ets.timestamp() < armed:
            reason = "skipped_prearm"
        elif not settings.tf_alerts_enabled(tf):
            reason = "skipped_tf"
        elif ev["kind"] in ("be", "exit"):
            if S.notify_status(conn, zdef["id"], "entry") not in ("sent", "dry"):
                reason = "skipped_noentry"
        else:
            lim = max_age_sec(ev["kind"], tf)
            if lim is not None and (ctx.now - ets).total_seconds() > lim:
                reason = "skipped_stale"
            elif ev["kind"] == "touch":
                if ctx.touch_budget <= 0:
                    reason = "skipped_burst"
                else:
                    ctx.touch_budget -= 1
        if reason:
            S.claim(conn, zdef["id"], key, ev["ts"], reason)
            ctx.skipped[reason] = ctx.skipped.get(reason, 0) + 1
            continue
        text = format_event(zdef, ev, res)
        if not S.claim(conn, zdef["id"], key, ev["ts"], "pending", text):
            continue
        from ..core.telegram import send_telegram

        out = send_telegram(text, settings=settings)
        if not out.get("dry_run"):
            time.sleep(1.05)  # Telegram: stay under ~1 msg/s per chat (no 429 on bursts)
        status = ("dry" if out.get("dry_run") else "sent") if out.get("ok") else "error"
        S.set_notify_status(conn, zdef["id"], key, status)
        ctx.sent.append({"zone": zdef["id"], "event": key, "status": status})


def _keep(res: dict, was_stored: bool) -> bool:
    if was_stored or res.get("trade"):
        return True
    if any(t["score"] >= P.MIN_STARS for t in res.get("touches") or []):
        return True
    return res["state"] in LIVE_STATES and res.get("score", 0) >= P.MIN_STARS


def _process_symbol(conn, ctx: _Ctx, inst: Instrument, tf: str, armed: float | None,
                    only_ids: set[str] | None = None) -> dict[str, int]:
    settings = ctx.settings
    htf = read_cache(settings.cache_dir, inst.id, tf)
    if htf is None or htf.empty:
        return {"zones": 0}
    htf = norm_index(htf)
    htf = htf[~htf.index.duplicated(keep="last")].sort_index()
    ltf_tf = P.LOWER_TF[tf]
    all_rows = S.stored_zones(conn, symbol=inst.id, tf=tf)
    stored = {r["id"]: json.loads(r["def"]) for r in all_rows if r["state"] in LIVE_STATES}
    final_ids = {r["id"] for r in all_rows if r["state"] not in LIVE_STATES}
    if only_ids is not None:
        zdefs = {k: v for k, v in stored.items() if k in only_ids}
    else:
        zdefs = {z["id"]: z for z in detect_zones(htf, tf, inst.id, inst.group, now=ctx.now)
                 if z["id"] not in final_ids}
        zdefs.update(stored)  # vanished fix: a stored live zone is always re-checked
    if not zdefs:
        return {"zones": 0}
    ltf = norm_index(read_cache(settings.cache_dir, inst.id, ltf_tf))
    results = {zid: simulate_zone(z, htf, ltf, ctx.now) for zid, z in zdefs.items()}
    need = [zid for zid, r in results.items() if r["state"] in TRADE_STATES]
    if need and ctx.fetch_ltf and not _fresh_enough(ltf, ltf_tf, ctx.now) and (inst.id, ltf_tf) not in ctx.fetched:
        ctx.fetched.add((inst.id, ltf_tf))
        if _fetch(inst, ltf_tf, settings, limit=1000 if ltf_tf == "M1" else 300):
            ltf = norm_index(read_cache(settings.cache_dir, inst.id, ltf_tf))
            for zid in need:
                results[zid] = simulate_zone(zdefs[zid], htf, ltf, ctx.now)
    n_live = 0
    for zid, res in results.items():
        if not _keep(res, zid in stored):
            continue
        S.upsert_zone(conn, zdefs[zid], res)
        if res["state"] in LIVE_STATES and res["score"] >= P.MIN_STARS:
            n_live += 1
        _emit(conn, ctx, zdefs[zid], res, armed)
    conn.commit()
    return {"zones": n_live}


def refresh_tf(tf: str, *, settings: Settings | None = None, now: pd.Timestamp | None = None,
               notify: bool = True, fetch_ltf: bool = True, symbols: list[str] | None = None) -> dict[str, Any]:
    """One TF: detect + simulate every universe symbol from the cache, persist, alert.
    First run of a TF = silent warm-up (go-live guard: only events after arming alert)."""
    settings = settings or get_settings()
    now = now or _utcnow()
    t0 = time.time()
    conn = S.connect(settings.db_path)
    try:
        armed = _armed_ts(conn, tf)
        warmup = armed is None
        ctx = _Ctx(settings, now, notify and not warmup, fetch_ltf)
        by_group: dict[str, int] = {}
        errors = []
        for inst in universe(settings):
            if symbols and inst.id not in symbols:
                continue
            try:
                r = _process_symbol(conn, ctx, inst, tf, armed)
                by_group[inst.group] = by_group.get(inst.group, 0) + r["zones"]
            except Exception as e:
                errors.append(f"{inst.id}: {type(e).__name__}: {e}"[:200])
        if warmup:
            S.meta_set(conn, f"armed_{tf}", str(now.timestamp()))
            if not S.meta_get(conn, "go_live"):
                S.meta_set(conn, "go_live", now.isoformat())
        return {"tf": tf, "zones": sum(by_group.values()), "by_group": by_group, "warmup": warmup,
                "sent": ctx.sent, "skipped": ctx.skipped, "errors": errors[:10],
                "elapsed_sec": round(time.time() - t0, 1)}
    finally:
        conn.close()


def track_open(*, settings: Settings | None = None, now: pd.Timestamp | None = None,
               skip_tfs: list[str] | None = None, notify: bool = True) -> dict[str, Any]:
    """Every tick: zones waiting for a trigger or holding a trade (any TF) get their lower
    TF refreshed and are re-simulated, so ENTRÉE / +1R / résultat are not delayed by the
    slow cadence of H4/D/W."""
    settings = settings or get_settings()
    now = now or _utcnow()
    t0 = time.time()
    conn = S.connect(settings.db_path)
    try:
        rows = S.stored_zones(conn, states=TRADE_STATES)
        insts = {i.id: i for i in universe(settings)}
        todo: dict[tuple[str, str], set[str]] = {}
        for r in rows:
            if skip_tfs and r["tf"] in skip_tfs:
                continue
            if r["symbol"] in insts:
                todo.setdefault((r["symbol"], r["tf"]), set()).add(r["id"])
        ctx = _Ctx(settings, now, notify, True)
        errors = []
        for (sym, tf), ids in todo.items():
            armed = _armed_ts(conn, tf)
            if armed is None:
                continue
            try:
                _process_symbol(conn, ctx, insts[sym], tf, armed, only_ids=ids)
            except Exception as e:
                errors.append(f"{sym} {tf}: {e}"[:200])
        return {"tracked": sum(len(v) for v in todo.values()), "sent": ctx.sent, "skipped": ctx.skipped,
                "errors": errors, "elapsed_sec": round(time.time() - t0, 1)}
    finally:
        conn.close()


# ------------------------------------------------------------------ views
def to_api(row) -> dict[str, Any]:
    z = json.loads(row["def"])
    r = json.loads(row["result"])
    st = r.get("stars") or {}
    bull = z["direction"] == "bull"
    prox = z["high"] if bull else z["low"]
    sl = r.get("sl")
    tr = r.get("trade") or {}
    risk = abs(prox - sl) if sl is not None else None
    entry = tr.get("entry", prox)
    tp = tr.get("tp") if tr else (prox + (2 if bull else -2) * risk if risk else None)
    last = r.get("last_close")
    dist_atr = 0.0
    if last is not None and z["atr"]:
        gap = (last - prox) if bull else (prox - last)
        dist_atr = round(max(gap, 0.0) / z["atr"], 2)
    touches = r.get("touches") or []
    return {
        "id": z["id"], "symbol": z["symbol"], "group": z.get("group"), "tf": z["tf"],
        "direction": z["direction"], "ts_ob": z["ts_ob"], "ts_bos": z.get("armed_ts"),
        "low": z["low"], "high": z["high"], "open": None, "close": None,
        "score": int(r.get("score") or 0),
        "stars": {k: bool(st.get(k)) for k in ("tendance", "liquidite", "vierge", "fibo", "session")},
        "star1_fvg": True, "star2_trend": bool(st.get("tendance")), "star3_fib": bool(st.get("fibo")),
        "star4_liquidity": bool(st.get("liquidite")), "star5_session": bool(st.get("session")),
        "star_virgin": bool(st.get("vierge")), "star5_pending": False, "fresh": bool(st.get("vierge")),
        "trend": z.get("trend"), "entry": entry, "sl": tr.get("sl", sl), "tp1": None, "tp2": tp,
        "rr_tp1": None, "rr_tp2": P.TP_R, "atr": z["atr"], "fib_eq": r.get("fib_eq"),
        "swing_low": None, "swing_high": None, "distance_atr": dist_atr, "last_close": last,
        "session_label": "session EU/US" if z.get("star_session") else None,
        "sweep": bool(z.get("star_liquidity")), "fvg_low": z.get("fvg_low"), "fvg_high": z.get("fvg_high"),
        "state": r["state"], "status": UI_STATUS.get(r["state"], r["state"]),
        "touched_at": touches[0]["ts"] if touches else None, "n_touch": r.get("n_touch", 0),
        "ltf": r.get("ltf"), "invalidated_at": r.get("invalidated_ts"), "expired_at": r.get("expired_ts"),
        "trade_status": tr.get("status") if tr else None, "trade_r": tr.get("r_net") if tr else None,
        "trade_r_gross": tr.get("r_gross") if tr else None, "trade_exit": tr.get("exit") if tr else None,
        "trade_fill_at": tr.get("entry_ts") if tr else None, "trade_exit_at": tr.get("exit_ts") if tr else None,
        "trade_be_at": tr.get("be_ts") if tr else None, "trade_trigger": tr.get("trigger") if tr else None,
        "trade_tp": tr.get("tp") if tr else None,
        "entry_note": "clôture de la bougie de retournement (au marché)" if not tr else "entrée réelle",
    }


def list_zones(*, tf: str | None = None, group: str | list[str] | None = None, symbol: str | None = None,
               statuses: list[str] | None = None, min_score: int = P.MIN_STARS, active_only: bool = False,
               limit: int = 200, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    conn = S.connect(settings.db_path)
    try:
        rows = S.stored_zones(conn, tf=tf, symbol=symbol.upper() if symbol else None)
    finally:
        conn.close()
    if isinstance(group, str):
        group = [g.strip().upper() for g in group.split(",") if g.strip() and g.strip().upper() != "ALL"]
    out = []
    for r in rows:
        if group and (r["grp"] or "") not in group:
            continue
        if active_only and r["state"] not in ("active", "touched", "waiting"):
            continue
        z = to_api(r)
        if statuses and z["status"] not in statuses and z["state"] not in statuses:
            continue
        # live zones: current score; past zones: score at their (last) touch
        if z["state"] in LIVE_STATES and z["score"] < min_score:
            continue
        out.append(z)
    out.sort(key=lambda z: (z["touched_at"] or z["ts_ob"]), reverse=True)
    return out[:limit]


def _summ(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "wr": None, "avg_r": None, "sum_r": 0.0, "exits": {}}
    rs = [r["r_net"] for r in rows]
    exits: dict[str, int] = {}
    for r in rows:
        exits[r["exit"]] = exits.get(r["exit"], 0) + 1
    return {"n": n, "wins": exits.get("tp", 0), "wr": round(exits.get("tp", 0) / n, 3),
            "avg_r": round(float(np.mean(rs)), 3), "sum_r": round(float(np.sum(rs)), 2), "exits": exits}


def compute_stats(tf: str | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    conn = S.connect(settings.db_path)
    try:
        rows = [dict(r) for r in S.stored_zones(conn, tf=tf)]
        go_live = S.meta_get(conn, "go_live")
        notif = conn.execute("SELECT status, COUNT(*) n FROM v3_notify GROUP BY status").fetchall()
    finally:
        conn.close()
    closed = [r for r in rows if r["r_net"] is not None]
    entries = [r for r in rows if r["entry_ts"]]
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1

    def per_day(rs):
        if not rs:
            return None
        first = min(pd.Timestamp(r["entry_ts"]) for r in rs)
        days = max(1, int(np.busday_count(first.date(), _utcnow().date())) + 1)
        return round(len(rs) / days, 2)

    def block(rs_closed, rs_entries):
        out = _summ(rs_closed)
        out["entries"] = len(rs_entries)
        out["open"] = sum(1 for r in rs_entries if r["exit"] is None)
        out["entries_per_day"] = per_day(rs_entries)
        out["by_tf"] = {k: _summ([r for r in rs_closed if r["tf"] == k]) for k in sorted({r["tf"] for r in rs_closed})}
        out["by_group"] = {k: _summ([r for r in rs_closed if r["grp"] == k]) for k in sorted({r["grp"] for r in rs_closed})}
        return out

    live_c = [r for r in closed if go_live and r["entry_ts"] >= go_live]
    live_e = [r for r in entries if go_live and r["entry_ts"] >= go_live]
    bt = None
    try:
        from pathlib import Path

        bt = json.loads((Path(__file__).parent / "backtest_summary.json").read_text())
    except Exception:
        pass
    return {
        "engine": "v3 Kasper",
        "method": "Entrée = clôture bougie de retournement LTF · SL au-delà de l'OB (+0.05 ATR) · TP +2R · "
                  "SL au point d'entrée à +1R · pas de time stop · R net de frais (spread+commission+slippage)",
        "go_live": go_live,
        "n_zones": len(rows),
        "by_state": by_state,
        "cache": block(closed, entries),
        "live": block(live_c, live_e),
        "notifications": {r["status"]: r["n"] for r in notif},
        "backtest": bt,
    }
