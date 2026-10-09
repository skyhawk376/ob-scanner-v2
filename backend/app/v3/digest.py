"""Morning digest (07:45 Paris): live v3 stats + live zones. One message, no zone spam."""
from __future__ import annotations

from typing import Any

from ..core.config import Settings, get_settings
from ..core.telegram import send_telegram
from .service import compute_stats, list_zones


def build_digest(settings: Settings | None = None, label: str | None = None) -> str:
    st = compute_stats(settings=settings)
    live = st["live"]
    zones = list_zones(active_only=True, limit=5000, settings=settings)
    by_tf: dict[str, int] = {}
    for z in zones:
        by_tf[z["tf"]] = by_tf.get(z["tf"], 0) + 1
    tfs = " · ".join(f"{k} {v}" for k, v in by_tf.items()) or "aucune"
    wr = f"{live['wr']*100:.0f} %" if live.get("wr") is not None else "—"
    avg = f"{live['avg_r']:+.2f}R" if live.get("avg_r") is not None else "—"
    return (
        f"📋 OB Scanner v3 — récap {label or ''}\n"
        f"Zones ≥4★ actives : {len(zones)} ({tfs})\n"
        f"Trades live : {live['n']} clôturés · {live['open']} en cours · WR (TP) {wr} · moyenne {avg} net"
    )


def run_digest(*, settings: Settings | None = None, force_dry: bool | None = True, label: str | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    text = build_digest(settings, label)
    return {"text": text, **send_telegram(text, settings=settings, force_dry=force_dry)}
