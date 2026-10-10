"""Aérogest B23 watcher job: login → fleet → B23 plannings → diff → Telegram (dedicated bot).

Read-only: only GET login page, POST login, POST planning read endpoints. Never books.
Isolated from the trading scanner: every error is caught and logged.
"""
from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import state, telegram
from .client import AerogestClient
from .parse import JOURS, format_alert, is_b23, parse_aircraft_planning, parse_fleet

TZ = ZoneInfo("Europe/Paris")
_lock = threading.Lock()
_client: AerogestClient | None = None


def _env_bool(k: str, default: bool) -> bool:
    v = os.getenv(k)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def config() -> dict:
    return {
        "enabled": _env_bool("AEROGEST_ENABLED", True),
        "user": os.getenv("AEROGEST_USER", ""),
        "password": os.getenv("AEROGEST_PASSWORD", ""),
        "token": os.getenv("AEROGEST_TG_TOKEN", ""),
        "chat_id": os.getenv("AEROGEST_TG_CHAT_ID", "").strip(),
        "min_minutes": int(os.getenv("AEROGEST_MIN_MINUTES", "30")),
        # Club booking horizon (days ahead, inclusive). Aérogest exposes no setting; 60 days
        # matches the latest bookings observed (≈2 months). Override without code change.
        "horizon_days": int(os.getenv("AEROGEST_HORIZON_DAYS", "60")),
        "exclude_civil_night": _env_bool("AEROGEST_EXCLUDE_CIVIL_NIGHT", False),
        "hours": os.getenv("AEROGEST_HOURS", "7-22"),
    }


def _log(msg: str) -> None:
    print(f"[aerogest] {msg}", flush=True)


def resolve_chat_id(conn, cfg: dict, discover=telegram.discover_chat_id) -> str | None:
    if cfg["chat_id"]:
        return cfg["chat_id"]
    cid = state.get_meta(conn, "chat_id")
    if cid or not cfg["token"]:
        return cid
    cid = discover(cfg["token"])
    if cid:
        state.set_meta(conn, "chat_id", cid)
        _log(f"chat id discovered via /start: {cid}")
    return cid


def activation_text(b23: list[str], horizon: date, cfg: dict) -> str:
    return ("✅ Surveillance Aérogest B23 activée\n"
            f"Avions : {', '.join(b23) or '—'}\n"
            f"Horizon : jusqu'au {JOURS[horizon.weekday()]} {horizon:%d/%m/%Y}\n"
            f"Créneaux ≥ {cfg['min_minutes']} min · vérification toutes les 10 min, 07:00–22:00")


def _in_hours(now: datetime, spec: str) -> bool:
    a, b = (int(x) for x in spec.split("-"))
    return a * 60 <= now.hour * 60 + now.minute <= b * 60


def run_once(db_path, now: datetime | None = None, client=None, cfg: dict | None = None,
             sender=telegram.send, discover=telegram.discover_chat_id, force: bool = False) -> dict:
    global _client
    cfg = cfg or config()
    now = now or datetime.now(TZ)
    if not cfg["enabled"]:
        return {"skipped": "disabled"}
    if not force and not _in_hours(now, cfg["hours"]):
        return {"skipped": "outside hours"}
    if not _lock.acquire(blocking=False):
        return {"skipped": "already running"}
    conn = None
    res: dict = {"ok": False}
    try:
        conn = state.connect(db_path)
        if client is None:
            if not (cfg["user"] and cfg["password"]):
                raise RuntimeError("AEROGEST_USER/PASSWORD missing")
            if _client is None:
                _client = AerogestClient(cfg["user"], cfg["password"])
            client = _client
        today = now.date()
        horizon = today + timedelta(days=cfg["horizon_days"])
        fleet = parse_fleet(client.daily(today))
        b23 = [a for a in fleet if is_b23(a.type)]
        types = {a.reg: a.type for a in b23}
        first_run = state.get_meta(conn, "initialized") is None
        free_count, new_slots = 0, []
        naive_now = now.replace(tzinfo=None)
        for a in b23:
            days = {}
            start = today
            while start <= horizon:
                data = client.aircraft(a.id, start)
                for d, slots in parse_aircraft_planning(a.reg, data, cfg["min_minutes"],
                                                        cfg["exclude_civil_night"], naive_now).items():
                    if today <= d <= horizon:
                        days[d] = slots
                start += timedelta(days=30)
            free_count += sum(len(v) for v in days.values())
            new = state.apply_snapshot(conn, a.reg, days, cfg["min_minutes"], today)
            if not first_run:
                new_slots += new
        if first_run:
            state.set_meta(conn, "initialized", now.isoformat(timespec="seconds"))
        chat = resolve_chat_id(conn, cfg, discover)
        sent = 0
        if chat and cfg["token"]:
            if not state.get_meta(conn, f"activation_sent:{chat}"):
                if sender(cfg["token"], chat, activation_text([a.reg for a in b23], horizon, cfg)):
                    state.set_meta(conn, f"activation_sent:{chat}", now.isoformat(timespec="seconds"))
            for s in new_slots:
                if sender(cfg["token"], chat, format_alert(s, types.get(s.reg, "B23"))):
                    state.mark_alerted(conn, s)
                    sent += 1
        elif new_slots:
            _log(f"{len(new_slots)} new slot(s) but chat id unknown (waiting for /start) — not sent")
            for s in new_slots:  # don't burst old slots once the chat becomes known
                state.mark_alerted(conn, s)
        res = {"ok": True, "logged_in": bool(getattr(client, "logged_in", True)), "b23": [a.reg for a in b23],
               "horizon": horizon.isoformat(), "free_count": free_count, "new_count": len(new_slots),
               "sent": sent, "first_run": first_run, "chat_known": bool(chat)}
        _log(f"run ok b23={res['b23']} horizon={res['horizon']} free={free_count} "
             f"new={len(new_slots)} sent={sent} first_run={first_run} chat_known={bool(chat)}")
        state.log_run(conn, ok=1, b23=",".join(res["b23"]), horizon=res["horizon"],
                      free_count=free_count, new_count=len(new_slots), sent=sent)
    except Exception as e:  # never propagate into the scheduler / trading scanner
        err = f"{type(e).__name__}: {str(e)[:200]}"
        _log(f"run failed: {err}")
        res = {"ok": False, "error": err}
        if _client is not None:
            _client.logged_in = False
        try:
            if conn is not None:
                state.log_run(conn, ok=0, error=err)
        except Exception:
            pass
    finally:
        if conn is not None:
            conn.close()
        _lock.release()
    return res


def status(db_path) -> dict:
    conn = state.connect(db_path)
    try:
        runs = [dict(r) for r in conn.execute("SELECT * FROM aerogest_runs ORDER BY rowid DESC LIMIT 5")]
        n_alerts = conn.execute("SELECT COUNT(*) FROM aerogest_alerts").fetchone()[0]
        return {"enabled": config()["enabled"], "chat_known": bool(config()["chat_id"] or state.get_meta(conn, "chat_id")),
                "initialized": state.get_meta(conn, "initialized"), "alerts_recorded": n_alerts, "last_runs": runs}
    finally:
        conn.close()
