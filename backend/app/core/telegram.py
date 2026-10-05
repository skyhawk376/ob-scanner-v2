"""Telegram notifications with dry-run fallback."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import Settings, get_settings
from .store import connect, mark_notified, was_notified

PARIS = ZoneInfo("Europe/Paris")


def _stars(score: int) -> str:
    return "★" * int(score) + "☆" * max(0, 5 - int(score))


def format_zone_message(event: str, zone: dict[str, Any]) -> str:
    direction = zone.get("direction", "bull")
    label = "ZONE ACHAT" if direction == "bull" else "ZONE VENTE"
    score = int(zone.get("score") or 0)
    sess = zone.get("touched_session") or zone.get("session_label") or "—"
    lo, hi = zone.get("low"), zone.get("high")
    entry, sl, tp1 = zone.get("entry"), zone.get("sl"), zone.get("tp1")
    rr = zone.get("rr_tp1")
    rr_s = f"{rr:.1f}" if isinstance(rr, (int, float)) else "—"
    event_fr = {
        "new_zone": "Nouvelle zone",
        "touchee": "Premier contact",
        "reaction": "Réaction +1R",
        "echec": "Invalidation / SL",
        "digest": "Récap",
    }.get(event, event)
    return (
        f"{_stars(score)} {event_fr}\n"
        f"{label} {zone.get('symbol')} {zone.get('tf')}\n"
        f"· {lo:.4g}–{hi:.4g}\n"
        f"· Entrée {entry:.4g} · SL {sl:.4g} · TP1 {tp1 if tp1 is None else f'{tp1:.4g}'} (RR {rr_s})\n"
        f"· session {sess}"
    )


def _append_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def send_telegram(
    text: str,
    *,
    settings: Settings | None = None,
    force_dry: bool | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dry = settings.telegram_dry_run if force_dry is None else force_dry
    if not settings.telegram_configured:
        dry = True
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": now,
        "dry_run": dry,
        "chat_id": settings.telegram_chat_id or None,
        "text": text,
    }
    if dry:
        _append_log(settings.telegram_log_path, record)
        print(f"[telegram:dry-run] {text.replace(chr(10), ' | ')}")
        return {"ok": True, "dry_run": True, "path": str(settings.telegram_log_path)}

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": text},
            )
            data = resp.json()
            record["response"] = data
            _append_log(settings.telegram_log_path, record)
            return {"ok": bool(data.get("ok")), "dry_run": False, "response": data}
    except Exception as e:
        record["error"] = str(e)
        _append_log(settings.telegram_log_path, record)
        return {"ok": False, "dry_run": False, "error": str(e)}


def notify_zone_event(
    event: str,
    zone: dict[str, Any],
    *,
    settings: Settings | None = None,
    force_dry: bool | None = None,
    dedupe: bool = True,
) -> dict[str, Any] | None:
    """Send (or dry-run) a zone event; dedupe via notify_log."""
    settings = settings or get_settings()
    zid = zone.get("id") or ""
    if not zid:
        return None

    # Rules (PLAN §9)
    score = int(zone.get("score") or 0)
    if score < 4 and event != "digest":
        return None

    if event == "new_zone":
        tf = str(zone.get("tf", "")).upper()
        sym = zone.get("symbol")
        # H4/D/W always; H1 only XAUUSD
        if tf == "H1" and sym != "XAUUSD":
            return None

    if event == "touchee":
        # London/NY only (except we still allow if session set; crypto same rule per PLAN default)
        sess = zone.get("touched_session")
        if sess not in ("London", "NY"):
            return None

    conn = connect(settings.db_path)
    try:
        if dedupe and was_notified(conn, zid, event):
            return {"ok": True, "skipped": "duplicate"}
        text = format_zone_message(event, zone)
        result = send_telegram(text, settings=settings, force_dry=force_dry)
        if result.get("ok") and dedupe:
            mark_notified(conn, zid, event)
        return result
    finally:
        conn.close()


def build_digest(zones: list[dict[str, Any]], *, label: str) -> str:
    near = [
        z
        for z in zones
        if int(z.get("score") or 0) >= 4
        and (z.get("status") or "active") == "active"
        and float(z.get("distance_atr") or 99) <= 1.5
    ]
    near.sort(key=lambda z: (0 if z.get("symbol") == "XAUUSD" else 1, z.get("distance_atr", 99)))
    lines = [f"📋 Récap {label} (Europe/Paris)", f"{len(near)} zone(s) ≥4★ à <1,5 ATR :"]
    if not near:
        lines.append("· aucune pour le moment")
    for z in near[:15]:
        d = "ACHAT" if z.get("direction") == "bull" else "VENTE"
        lines.append(
            f"· {_stars(int(z.get('score') or 0))} {z.get('symbol')} {z.get('tf')} {d} "
            f"({float(z.get('distance_atr') or 0):.2f} ATR)"
        )
    return "\n".join(lines)


def run_digest(*, settings: Settings | None = None, force_dry: bool = True, label: str | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    from .store import list_zones

    conn = connect(settings.db_path)
    try:
        zones = list_zones(conn, min_score=4, limit=2000)
    finally:
        conn.close()
    now_paris = datetime.now(PARIS).strftime("%H:%M")
    text = build_digest(zones, label=label or now_paris)
    return send_telegram(text, settings=settings, force_dry=force_dry)
