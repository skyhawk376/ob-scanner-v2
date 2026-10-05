"""Pure tool implementations (no MCP transport) — used by server + smoke tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.cache import read_cache
from ..core.config import get_settings
from ..core.monitor import compute_stats
from ..core.scanner import load_stored_zones, run_scan
from ..core.store import connect
from .chart_svg import write_zone_chart

ROOT = Path(__file__).resolve().parents[3]


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)


def tool_list_zones(
    tf: str | None = None,
    group: str | None = None,
    min_stars: int = 4,
    status: str | None = None,
    limit: int = 50,
) -> str:
    st = None
    sts = None
    if status:
        parts = [s.strip() for s in status.split(",") if s.strip()]
        if len(parts) == 1:
            st = parts[0]
        elif len(parts) > 1:
            sts = parts
    zones = load_stored_zones(
        tf=tf.upper() if tf else None,
        group=group,
        min_score=min_stars,
        status=st,
        statuses=sts,
        limit=limit,
    )
    # slim payload for LLM context
    slim = [
        {
            "id": z.get("id"),
            "symbol": z.get("symbol"),
            "tf": z.get("tf"),
            "direction": z.get("direction"),
            "score": z.get("score"),
            "status": z.get("status", "active"),
            "low": z.get("low"),
            "high": z.get("high"),
            "entry": z.get("entry"),
            "sl": z.get("sl"),
            "tp1": z.get("tp1"),
            "rr_tp1": z.get("rr_tp1"),
            "distance_atr": z.get("distance_atr"),
            "session_label": z.get("session_label") or z.get("touched_session"),
            "touched_at": z.get("touched_at"),
            "stars": {
                "fvg": z.get("star1_fvg"),
                "trend": z.get("star2_trend"),
                "fib": z.get("star3_fib"),
                "liquidity": z.get("star4_liquidity"),
                "session": z.get("star5_session"),
            },
        }
        for z in zones
    ]
    return _json({"n": len(slim), "zones": slim})


def tool_get_zone(zone_id: str) -> str:
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        row = conn.execute("SELECT payload FROM zones WHERE id=?", (zone_id,)).fetchone()
        if not row:
            # try LIKE on symbol|tf prefix
            row = conn.execute(
                "SELECT payload FROM zones WHERE id LIKE ? LIMIT 1",
                (f"%{zone_id}%",),
            ).fetchone()
        if not row:
            return _json({"error": f"zone not found: {zone_id}"})
        return row["payload"] if isinstance(row["payload"], str) else _json(dict(row))
    finally:
        conn.close()


def tool_scan_now(tf: str = "H1", group: str | None = None, min_stars: int = 4) -> str:
    tf = tf.upper()
    if tf not in ("H1", "H4", "D", "W"):
        return _json({"error": f"unsupported tf {tf}"})
    groups = get_settings().resolved_scan_groups(group)
    summary = run_scan(
        tfs=[tf],
        groups=groups,
        min_score=min_stars,
        require_fresh=True,
        persist=True,
    )
    return _json(
        {
            "tf": tf,
            "elapsed_sec": round(summary.elapsed_sec, 2),
            "n_zones": len(summary.zones),
            "symbols_ok": sum(1 for s in summary.per_symbol if s.ok),
            "top": [
                {
                    "id": z.id,
                    "symbol": z.symbol,
                    "direction": z.direction,
                    "score": z.score,
                    "distance_atr": z.distance_atr,
                }
                for z in summary.zones[:15]
            ],
        }
    )


def tool_get_stats(tf: str | None = None) -> str:
    stats = compute_stats(tf=tf.upper() if tf else None)
    return _json(stats)


def tool_get_candles(symbol: str, tf: str = "H1", n: int = 100) -> str:
    settings = get_settings()
    df = read_cache(settings.cache_dir, symbol.upper(), tf.upper())
    if df is None or df.empty:
        return _json({"error": f"no cache for {symbol} {tf}"})
    if len(df) > n:
        df = df.iloc[-n:]
    candles = []
    for ts, row in df.iterrows():
        candles.append(
            {
                "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
    return _json({"symbol": symbol.upper(), "tf": tf.upper(), "n": len(candles), "candles": candles})


def tool_get_chart_svg(zone_id: str, bars: int = 80) -> str:
    """Write SVG next to results; return path + inline svg (truncated if huge)."""
    settings = get_settings()
    raw = tool_get_zone(zone_id)
    try:
        zone = json.loads(raw)
    except json.JSONDecodeError:
        return _json({"error": "invalid zone payload"})
    if zone.get("error"):
        return raw

    df = read_cache(settings.cache_dir, zone["symbol"], zone["tf"])
    if df is None or df.empty:
        return _json({"error": "no candles for chart"})
    if len(df) > bars:
        df = df.iloc[-bars:]
    candles = [
        {
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for _, r in df.iterrows()
    ]
    safe = zone["id"].replace("|", "_").replace(":", "-").replace("/", "-")[:120]
    out = Path(settings.results_dir) / "charts" / f"{safe}.svg"
    write_zone_chart(out, candles, zone)
    svg = out.read_text(encoding="utf-8")
    return _json(
        {
            "path": str(out),
            "symbol": zone.get("symbol"),
            "tf": zone.get("tf"),
            "svg_chars": len(svg),
            "svg_preview": svg[:1500] + ("…" if len(svg) > 1500 else ""),
            "note": "Fichier SVG local — alternative légère à PNG (pas de matplotlib).",
        }
    )
