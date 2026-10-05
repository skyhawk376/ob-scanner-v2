"""FastAPI — P0–P4 (data, scan, candles, lifecycle, telegram)."""
from __future__ import annotations

from typing import Literal

from pathlib import Path as FsPath

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..core.cache import read_cache
from ..core.config import get_settings
from ..core.fetcher import fetch_all
from ..core.monitor import compute_stats, refresh_statuses
from ..core.scanner import load_stored_zones, run_scan
from ..core.symbols import count_by_group, load_instruments
from ..core.telegram import run_digest, send_telegram
from ..providers.registry import ProviderHub

app = FastAPI(
    title="OB 5-star Scanner",
    version="0.5.0",
    description="Phase 5 — MCP + lifecycle + Telegram.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _maybe_scheduler():
    settings = get_settings()
    if not settings.enable_scheduler:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        sched = BackgroundScheduler(timezone=settings.tz)
        sched.add_job(
            lambda: refresh_statuses(tf="H1", notify=True, force_dry_telegram=None),
            "interval",
            minutes=2,
            id="monitor_h1",
            replace_existing=True,
        )
        sched.add_job(
            lambda: run_digest(force_dry=None, label="07:45 pré-Londres"),
            CronTrigger(hour=7, minute=45, timezone=settings.tz),
            id="digest_london",
            replace_existing=True,
        )
        sched.add_job(
            lambda: run_digest(force_dry=None, label="14:15 pré-NY"),
            CronTrigger(hour=14, minute=15, timezone=settings.tz),
            id="digest_ny",
            replace_existing=True,
        )
        sched.start()
        app.state.scheduler = sched
    except Exception as e:
        print(f"[scheduler] not started: {e}")


@app.get("/health")
def health():
    """Lightweight — avoid providers/network so PA WSGI never hangs on probe."""
    settings = get_settings()
    try:
        instruments = load_instruments(settings.symbols_yaml)
        n = len(instruments)
        by_group = count_by_group(instruments)
    except Exception as e:
        return {"status": "degraded", "phase": "P5", "error": str(e)}
    return {
        "status": "ok",
        "phase": "P5",
        "symbols": n,
        "by_group": by_group,
        "oanda_configured": bool(settings.oanda_api_key.strip()),
        "telegram_configured": settings.telegram_configured,
        "telegram_dry_run": settings.telegram_dry_run or not settings.telegram_configured,
        "cache_dir": str(settings.cache_dir),
        "tz": settings.tz,
    }


@app.get("/symbols")
def list_symbols():
    settings = get_settings()
    instruments = load_instruments(settings.symbols_yaml)
    return [
        {
            "id": i.id,
            "group": i.group,
            "primary": i.primary,
            "oanda": i.oanda,
            "yf": i.yf,
            "bn": i.bn,
            "priority": i.priority,
        }
        for i in instruments
    ]


@app.post("/fetch")
def fetch_endpoint(
    tf: Literal["H1", "H4", "D", "W"] = Query("H1"),
    group: str | None = Query(None),
    limit: int = Query(500, ge=50, le=5000),
):
    groups = [g.strip() for g in group.split(",")] if group else None
    summary = fetch_all(tfs=[tf], groups=groups, limit=limit, write=True)
    return {
        "tf": tf,
        "ok": summary.ok_count,
        "fail": summary.fail_count,
        "elapsed_sec": round(summary.elapsed_sec, 2),
        "by_source": summary.by_source(),
    }


@app.post("/scan")
def scan_endpoint(
    tf: Literal["H1", "H4", "D", "W"] = Query("H1"),
    group: str | None = Query(None),
    symbols: str | None = Query(None),
    min_score: int = Query(4, ge=1, le=5),
    include_mitigated: bool = Query(False),
):
    groups = [g.strip() for g in group.split(",")] if group else None
    syms = [s.strip() for s in symbols.split(",")] if symbols else None
    summary = run_scan(
        tfs=[tf],
        groups=groups,
        symbols=syms,
        min_score=min_score,
        require_fresh=not include_mitigated,
        persist=True,
    )
    return {
        "tf": tf,
        "elapsed_sec": round(summary.elapsed_sec, 2),
        "n_zones": len(summary.zones),
        "symbols_scanned": len(summary.per_symbol),
        "symbols_ok": sum(1 for s in summary.per_symbol if s.ok),
        "zones": [z.to_dict() for z in summary.zones],
    }


@app.get("/zones")
def zones_endpoint(
    tf: str | None = Query(None),
    group: str | None = Query(None),
    symbol: str | None = Query(None),
    status: str | None = Query(None, description="active|touchee|reaction|echec|expiree"),
    statuses: str | None = Query(None, description="comma-separated statuses"),
    min_score: int = Query(4, ge=1, le=5),
    limit: int = Query(200, ge=1, le=5000),
    active_only: bool = Query(False),
):
    st_list = [s.strip() for s in statuses.split(",")] if statuses else None
    zones = load_stored_zones(
        tf=tf,
        min_score=min_score,
        symbol=symbol,
        group=group,
        status=status,
        statuses=st_list,
        limit=limit,
        active_only=active_only,
    )
    return {"n": len(zones), "zones": zones}


@app.get("/candles/{symbol}")
def candles_endpoint(
    symbol: str,
    tf: Literal["H1", "H4", "D", "W"] = Query("H1"),
    limit: int = Query(200, ge=20, le=5000),
):
    settings = get_settings()
    df = read_cache(settings.cache_dir, symbol.upper(), tf)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No cache for {symbol} {tf}")
    if len(df) > limit:
        df = df.iloc[-limit:]
    candles = []
    for ts, row in df.iterrows():
        t = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
        candles.append(
            {
                "time": t,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
    return {"symbol": symbol.upper(), "tf": tf, "n": len(candles), "candles": candles}


@app.post("/refresh")
def refresh_endpoint(
    tf: Literal["H1", "H4", "D", "W"] = Query("H1"),
    history: bool = Query(
        False,
        description="Re-detect including mitigated and classify lifecycle (for Touches/Réaction)",
    ),
    group: str | None = Query(None),
    min_score: int = Query(4, ge=1, le=5),
    notify: bool = Query(True),
    dry_run: bool = Query(True),
):
    groups = [g.strip() for g in group.split(",")] if group else None
    summary = refresh_statuses(
        tf=tf,
        history=history,
        groups=groups,
        min_score=min_score,
        notify=notify,
        force_dry_telegram=dry_run,
    )
    return {
        "mode": summary.mode,
        "elapsed_sec": round(summary.elapsed_sec, 2),
        "n_zones": summary.n_zones,
        "updated": summary.updated,
        "by_status": summary.by_status,
        "transitions": len(summary.transitions),
        "notifications": summary.notifications,
    }


@app.get("/stats")
def stats_endpoint(tf: str | None = Query(None)):
    return compute_stats(tf=tf)


@app.post("/telegram/digest")
def telegram_digest(dry_run: bool = Query(True), label: str = Query("manual")):
    return run_digest(force_dry=dry_run, label=label)


@app.post("/telegram/test")
def telegram_test(dry_run: bool = Query(True)):
    return send_telegram(
        "OB Scanner — test Telegram (dry-run OK)" if dry_run else "OB Scanner — test Telegram",
        force_dry=dry_run,
    )


@app.get("/mcp/tools")
def mcp_tools():
    """Live MCP tool catalog + Claude Desktop run hint."""
    from ..mcp.catalog import TOOL_CATALOG
    from pathlib import Path as P

    settings = get_settings()
    venv_py = str(P(settings.symbols_yaml).resolve().parent / ".venv" / "bin" / "python")
    backend = str(P(settings.symbols_yaml).resolve().parent / "backend")
    return {
        "status": "ready",
        "phase": "P5",
        "transport": ["stdio"],
        "tools": TOOL_CATALOG,
        "note": "Lecture / scan local uniquement — aucun ordre. get_chart_svg (SVG) remplace PNG.",
        "run": {
            "command": venv_py,
            "args": ["-m", "app.mcp.server"],
            "cwd": backend,
        },
        "claude_desktop": {
            "mcpServers": {
                "ob-scanner": {
                    "command": venv_py,
                    "args": ["-m", "app.mcp.server"],
                    "cwd": backend,
                }
            }
        },
    }


# Optional: serve Vite build at /app when frontend/dist exists (Docker / single-process host)
_FRONT = FsPath(__file__).resolve().parents[3] / "frontend" / "dist"
if _FRONT.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONT / "assets"), name="assets")

    @app.get("/")
    def spa_index():
        index = _FRONT / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "frontend not built")

