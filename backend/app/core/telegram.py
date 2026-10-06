"""Telegram notifications with dry-run fallback."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import Settings, get_settings
from .store import claim_notify, connect

PARIS = ZoneInfo("Europe/Paris")


def _stars(score: int) -> str:
    return "★" * int(score) + "☆" * max(0, 5 - int(score))


def _reaction_r() -> float:
    from .lifecycle import reaction_r_from_env

    return reaction_r_from_env()


def _fmt_r(r: float) -> str:
    return f"{r:g}"


def _tp_levels(
    zone: dict[str, Any], *, bull: bool, tp_r: float | None = None
) -> tuple[float | None, float | None, float | None]:
    """Return (entry, sl, tp_at_+NR) for Telegram display, N = REACTION_R (live 2.0).

    Zone.tp1 may be distant opposing liquidity (RR >> N) — never show that as the trade RR.
    """
    tp_r = _reaction_r() if tp_r is None else float(tp_r)
    entry, sl = zone.get("entry"), zone.get("sl")
    if not isinstance(entry, (int, float)) or not isinstance(sl, (int, float)):
        return None, None, None
    risk = abs(float(entry) - float(sl))
    if risk <= 0:
        return float(entry), float(sl), None
    tp = float(entry) + tp_r * risk if bull else float(entry) - tp_r * risk
    return float(entry), float(sl), tp


# Backwards-compatible alias (old name)
def _tp_1r_levels(zone: dict[str, Any], *, bull: bool):
    return _tp_levels(zone, bull=bull)


_TRADE_EXIT_FR = {"tp": "TP", "sl": "SL", "time": "time stop 1h"}


def trade_line(zone: dict[str, Any]) -> str | None:
    """Realistic trade outcome line (fill at mid required) for reaction/échec alerts."""
    st = zone.get("trade_status")
    if not st:
        return None
    if st == "closed" and zone.get("trade_r") is not None:
        why = _TRADE_EXIT_FR.get(str(zone.get("trade_exit")), str(zone.get("trade_exit")))
        return f"· Trade réel (fill mid, 1h max) : {why} {float(zone['trade_r']):+.2f}R"
    label = {
        "unfilled": "non rempli (mid jamais atteint)",
        "pending": "entrée mid pas encore atteinte",
        "open": "rempli, en cours",
    }.get(str(st), str(st))
    return f"· Trade réel : {label}"


def format_zone_message(event: str, zone: dict[str, Any]) -> str:
    from .trend_bias import bias_line

    direction = zone.get("direction", "bull")
    bull = direction == "bull"
    label = "ZONE ACHAT" if bull else "ZONE VENTE"
    score = int(zone.get("score") or 0)
    sess = zone.get("touched_session") or zone.get("session_label") or "—"
    lo, hi = zone.get("low"), zone.get("high")
    tp_r = _reaction_r()
    r_lbl = _fmt_r(tp_r)
    entry, sl, tp_n = _tp_levels(zone, bull=bull, tp_r=tp_r)
    # Entry label: mid = milieu OB; proximal = bull haut / bear bas
    entry_mode = (zone.get("entry_mode") or zone.get("meta", {}).get("entry_mode") or "").strip().lower()
    if not entry_mode:
        import os
        entry_mode = os.environ.get("ENTRY_MODE", "mid").strip().lower()
    if entry_mode == "mid":
        entry_edge = "milieu OB"
    else:
        entry_edge = "haut OB" if bull else "bas OB"
    event_fr = {
        "new_zone": "Nouvelle zone",
        "touchee": "Premier contact",
        "reaction": f"Réaction +{r_lbl}R",
        "echec": "Invalidation / SL",
        "digest": "Récap",
    }.get(event, event)
    if entry is None or sl is None:
        levels = f"· Entrée — · SL — · TP(+{r_lbl}R) — (RR —)"
    elif tp_n is None:
        levels = (
            f"· Entrée {entry:.6g} ({entry_edge}) · SL {sl:.6g} (au-delà bord distal) · "
            f"TP(+{r_lbl}R) — (RR —)"
        )
    else:
        levels = (
            f"· Entrée {entry:.6g} ({entry_edge}) · SL {sl:.6g} (au-delà bord distal) · "
            f"TP(+{r_lbl}R) {tp_n:.6g} (RR {tp_r:.1f})"
        )
    lines = [
        f"{_stars(score)} {event_fr}",
        f"{label} {zone.get('symbol')} {zone.get('tf')}",
        f"· {lo:.6g}–{hi:.6g}",
        levels,
        bias_line(zone),
        f"· session {sess}",
    ]
    if event in ("reaction", "echec"):
        tl = trade_line(zone)
        if tl:
            lines.append(tl)
    return "\n".join(lines)


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

    # Filtre B: never notify outside the live universe (NQ100 / ENERGIE off)
    if settings.strategy_lock:
        from .symbols import load_instruments

        gmap = {i.id: i.group for i in load_instruments(settings.symbols_yaml)}
        if not settings.zone_in_strategy(gmap.get(str(zone.get("symbol") or "")), score):
            return {"ok": True, "skipped": "outside_strategy"}

    # new_zone: all TFs/symbols with score≥4 (H1 no longer XAU-only)
    # touchee: all sessions (no London/NY filter)
    # reaction / echec: unchanged (score≥4 only)

    conn = connect(settings.db_path)
    try:
        # Claim BEFORE send (UNIQUE zone_id+event). Prevents duplicate Telegram
        # when refresh/pipeline overlap — especially reaction events (GBPAUD×3).
        if dedupe and not claim_notify(conn, zid, event):
            return {"ok": True, "skipped": "duplicate"}
        if "bias_h4" not in zone:
            # Informational only — never blocks the alert (missing data → "?").
            try:
                from .trend_bias import compute_bias, bias_at_for_zone

                zone = {
                    **zone,
                    **compute_bias(
                        str(zone.get("symbol")),
                        str(zone.get("direction", "bull")),
                        bias_at_for_zone(zone),
                        cache_dir=settings.cache_dir,
                    ),
                }
            except Exception:
                pass
        text = format_zone_message(event, zone)
        result = send_telegram(text, settings=settings, force_dry=force_dry)
        # Slot already claimed; keep it on send failure to avoid spam retries.
        if not result.get("ok") and dedupe:
            result = {**result, "claimed": True, "note": "notify slot kept after send failure"}
        return result
    finally:
        conn.close()


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _avg(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}R"


def stats_lines(real: dict[str, Any] | None, *, title: str) -> list[str]:
    """Digest lines for realistic stats (TP +NR / SL / time stop 1h, fill required)."""
    if not real:
        return []
    tpd = real.get("trades_per_day")
    al, nal = real.get("aligned") or {}, real.get("not_aligned") or {}
    return [
        f"📊 {title} (fill mid · TP +{_fmt_r(float(real.get('tp_r') or 2))}R · time stop 1h)",
        f"· {real.get('n_closed', 0)} trades · WR {_pct(real.get('wr'))} · moy {_avg(real.get('avg_r'))}"
        + (f" · {tpd:.2f}/jour ouvré" if tpd is not None else "")
        + f" · {real.get('n_unfilled', 0)} non rempli(s)",
        f"· ✅ aligné H4+D1 : {al.get('n', 0)} · WR {_pct(al.get('wr'))} · moy {_avg(al.get('avg_r'))}",
        f"· ⚠️ non aligné : {nal.get('n', 0)} · WR {_pct(nal.get('wr'))} · moy {_avg(nal.get('avg_r'))}",
    ]


def build_digest(
    zones: list[dict[str, Any]], *, label: str, stats: dict[str, Any] | None = None
) -> str:
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
    if stats:
        lines += stats_lines(stats.get("realistic_7d"), title="Stats réelles 7 j")
        lines += stats_lines(stats.get("realistic"), title="Stats réelles (historique)")
    return "\n".join(lines)


def run_digest(*, settings: Settings | None = None, force_dry: bool = True, label: str | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    from .store import list_zones

    conn = connect(settings.db_path)
    try:
        zones = list_zones(conn, min_score=settings.clamp_min_score(4), limit=2000)
    finally:
        conn.close()
    if settings.strategy_lock:
        from .symbols import load_instruments

        gmap = {i.id: i.group for i in load_instruments(settings.symbols_yaml)}
        zones = [z for z in zones if settings.zone_in_strategy(gmap.get(z.get("symbol", "")), z.get("score"))]
    now_paris = datetime.now(PARIS).strftime("%H:%M")
    stats = None
    try:
        from .monitor import compute_stats

        stats = compute_stats(tf="H1", settings=settings)
    except Exception as e:  # digest must still go out
        print(f"[digest] stats unavailable: {e}", flush=True)
    text = build_digest(zones, label=label or now_paris, stats=stats)
    return send_telegram(text, settings=settings, force_dry=force_dry)
