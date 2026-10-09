"""Pure tool implementations (no MCP transport) — used by server + smoke tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.cache import read_cache
from ..core.config import get_settings
from ..v3 import store as v3store
from ..v3.service import compute_stats, list_zones as v3_list_zones, refresh_tf, to_api, universe
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
    """v3 zones. status: active|touchee|en_position|tp|sl|be|invalidee|expiree (comma list ok)."""
    from ..core.timeframes import normalize_tf

    sts = [x.strip() for x in status.split(",") if x.strip()] if status else None
    zones = v3_list_zones(
        tf=normalize_tf(tf) if tf else None,
        group=group,
        min_score=max(4, int(min_stars or 4)),
        statuses=sts,
        active_only=not sts,
        limit=limit,
    )
    keys = ("id", "symbol", "group", "tf", "direction", "score", "stars", "status", "low", "high",
            "entry", "sl", "tp2", "distance_atr", "touched_at", "ltf", "trade_trigger", "trade_exit",
            "trade_r", "trade_fill_at", "trade_be_at", "trade_exit_at")
    slim = [{k: z.get(k) for k in keys} for z in zones]
    return _json({"engine": "v3", "n": len(slim), "zones": slim})


def tool_get_zone(zone_id: str) -> str:
    settings = get_settings()
    conn = v3store.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM v3_zones WHERE id=?", (zone_id,)).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM v3_zones WHERE id LIKE ? ORDER BY ts_ob DESC LIMIT 1",
                               (f"%{zone_id}%",)).fetchone()
        if not row:
            return _json({"error": f"zone not found: {zone_id}"})
        z = to_api(row)
        z["result"] = json.loads(row["result"])
        return _json(z)
    finally:
        conn.close()


def tool_scan_now(tf: str = "H1", group: str | None = None, min_stars: int = 4) -> str:
    from ..core.timeframes import ALL_TFS, normalize_tf

    tf = normalize_tf(tf) or tf.upper()
    if tf not in ALL_TFS:
        return _json({"error": f"unsupported tf {tf}"})
    gl = [g.strip().upper() for g in group.split(",")] if group else None
    syms = [i.id for i in universe() if not gl or i.group in gl]
    rs = refresh_tf(tf, symbols=syms, fetch_ltf=False)
    zones = v3_list_zones(tf=tf, group=gl, min_score=max(4, min_stars), active_only=True, limit=15)
    return _json({
        "tf": tf, "elapsed_sec": rs["elapsed_sec"], "n_zones": rs["zones"], "by_group": rs["by_group"],
        "top": [{k: z[k] for k in ("id", "symbol", "direction", "score", "status", "distance_atr")} for z in zones],
    })


def tool_get_stats(tf: str | None = None) -> str:
    from ..core.timeframes import normalize_tf

    return _json(compute_stats(tf=normalize_tf(tf) if tf else None))


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
