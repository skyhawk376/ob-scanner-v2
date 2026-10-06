"""FastAPI — P0–P4 (data, scan, candles, lifecycle, telegram)."""
from __future__ import annotations

from typing import Literal

from pathlib import Path as FsPath

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..core.cache import cache_freshness, read_cache
from ..core.config import get_settings
from ..core.fetcher import fetch_all
from ..core.monitor import compute_stats, refresh_statuses
from ..core.scanner import load_stored_zones, run_scan
from ..core.symbols import count_by_group, load_instruments
from ..core.telegram import run_digest, send_telegram
from ..core.timeframes import ALL_TFS, normalize_tf
from ..providers.registry import ProviderHub

# Canonical TFs (M5 … W). Daily/Weekly aliases are normalised in _tf_or_400.
TfParam = Literal["M5", "M15", "M30", "H1", "H4", "D", "W"]


def _tf_opt(tf: str | None) -> str | None:
    """Optional TF filter (accepts aliases like Daily, 1W, 15m); 400 on unknown."""
    if tf is None or not str(tf).strip():
        return None
    t = normalize_tf(tf)
    if t is None:
        raise HTTPException(status_code=400, detail=f"tf inconnu: {tf} (attendu: {','.join(ALL_TFS)})")
    return t

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
    """Always-on hosts (Fly/Docker/VPS) set ENABLE_SCHEDULER=true.

    Jobs (single uvicorn worker → single scheduler):
      - pipeline (fetch → scan → refresh+notify) every FETCH_INTERVAL_MIN
      - daily history backfill (Touches / Réaction stats)
      - Telegram digests 07:45 / 14:15 Paris
      - bootstrap pipeline ~10 s after boot when cache is empty or stale
    PythonAnywhere uses wsgi.py (scheduler forced off) — unaffected.
    """
    settings = get_settings()
    if not settings.enable_scheduler:
        return
    try:
        from datetime import datetime, timedelta

        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        from ..core.jobs import run_pipeline

        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        settings.results_dir.mkdir(parents=True, exist_ok=True)

        sched = BackgroundScheduler(
            timezone=settings.tz,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )
        if settings.enable_fetch:
            from ..core.jobs import run_due

            # Tick every SCHED_TICK_MIN; each TF runs when its TF_SCHEDULE cadence is due
            # (M5 5 min · M15/H1 15 min · M30 30 min · H4 1 h · D 2 h · W 6 h by default).
            sched.add_job(
                lambda: run_due(trigger="schedule"),
                "interval",
                minutes=max(1, settings.sched_tick_min),
                id="pipeline",
                replace_existing=True,
            )
        else:
            # No live fetch: keep the old lightweight lifecycle monitor.
            sched.add_job(
                lambda: refresh_statuses(tf="H1", notify=True, force_dry_telegram=None),
                "interval",
                minutes=5,
                id="monitor_h1",
                replace_existing=True,
            )
        sched.add_job(
            lambda: run_pipeline(
                trigger="history", fetch=False, scan=False, history=True, notify=False
            ),
            CronTrigger(
                hour=settings.history_refresh_hour,
                minute=settings.history_refresh_minute,
                timezone=settings.tz,
            ),
            id="history_daily",
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
        if settings.enable_fetch:
            # Boot: run every due TF ~10 s after start (TFs with an empty cache get
            # BOOTSTRAP_LIMIT bars; a TF never run before is due immediately).
            sched.add_job(
                lambda: run_due(trigger="bootstrap"),
                "date",
                run_date=datetime.now(sched.timezone) + timedelta(seconds=10),
                id="bootstrap",
                replace_existing=True,
            )
        sched.start()
        app.state.scheduler = sched
        print(f"[scheduler] started jobs={[j.id for j in sched.get_jobs()]}", flush=True)
    except Exception as e:
        print(f"[scheduler] not started: {e}", flush=True)


@app.on_event("shutdown")
def _stop_scheduler():
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        try:
            sched.shutdown(wait=False)
        except Exception:
            pass


def _scheduler_info() -> dict:
    sched = getattr(app.state, "scheduler", None)
    if sched is None:
        return {"enabled": bool(get_settings().enable_scheduler), "running": False, "jobs": []}
    jobs = []
    for j in sched.get_jobs():
        nrt = getattr(j, "next_run_time", None)
        jobs.append({"id": j.id, "next_run": nrt.isoformat() if nrt else None})
    return {"enabled": True, "running": bool(sched.running), "jobs": jobs}


def _strategy_groups_or_400(group: str | None) -> list[str] | None:
    """Filtre B clamp for write/scan endpoints (STRATEGY_LOCK)."""
    groups = get_settings().clamp_groups(group)
    if groups is not None and not groups:
        raise HTTPException(
            status_code=400,
            detail=f"group hors Filtre B (autorisés: {','.join(get_settings().strategy_groups)})",
        )
    return groups


def _strategy_info() -> dict:
    s = get_settings()
    return {
        "name": "Filtre B",
        "locked": bool(s.strategy_lock),
        "groups": s.strategy_groups,
        "min_score": int(s.default_min_score),
        "entry_mode": (s.entry_mode or "mid").strip().lower(),
        "reaction_r": float(s.reaction_r),
        "soft_reaction": bool(s.enable_soft_reaction),
        "virgin_only": True,
        "tfs": s.pipeline_tfs if s.enable_fetch else list(ALL_TFS),
        "tf_schedule_min": s.tf_cadence,
        "alert_tfs": s.alert_tf_list,
    }


def _tf_status(settings) -> dict:
    """Per-TF last run (from tf_runs.json) + cadence — no disk scan of the cache."""
    from ..core.jobs import read_tf_runs

    runs = read_tf_runs(settings)
    out = {}
    for tf in settings.pipeline_tfs:
        r = runs.get(tf) or {}
        out[tf] = {
            "every_min": settings.tf_cadence.get(tf),
            "last_run": r.get("last_run"),
            "zones": r.get("zones"),
            "fetch_ok": r.get("fetch_ok"),
            "fetch_fail": r.get("fetch_fail"),
            "alerts": settings.tf_alerts_enabled(tf),
            "armed_at": r.get("armed_at"),
        }
    return out


@app.get("/strategy")
def strategy():
    """Live strategy universe (UI reads this to lock group / star chips)."""
    return _strategy_info()


@app.get("/healthz")
def healthz():
    """Liveness probe for Fly/Docker — no disk scan, no network."""
    return {"status": "ok"}


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
    cache_info = cache_freshness(settings.cache_dir, "H1")
    from ..core.jobs import read_status

    age = cache_info.get("age_sec")
    stale = age is None or age > settings.health_stale_sec
    pipeline = read_status(settings)
    last = pipeline.get("last") or {}
    return {
        "status": "stale" if (stale and settings.enable_scheduler) else "ok",
        "phase": "P5",
        "symbols": n,
        "by_group": by_group,
        "oanda_configured": bool(settings.oanda_api_key.strip()),
        "telegram_configured": settings.telegram_configured,
        "telegram_dry_run": settings.telegram_dry_run or not settings.telegram_configured,
        "cache_dir": str(settings.cache_dir),
        "cache_last_candle": cache_info.get("last_candle"),
        "cache_age_sec": cache_info.get("age_sec"),
        "tz": settings.tz,
        "cache_stale": stale,
        "scheduler": bool(settings.enable_scheduler),
        "scheduler_info": _scheduler_info(),
        "fetch_enabled": bool(settings.enable_fetch),
        "entry_mode": (settings.entry_mode or "mid").strip().lower(),
        "strategy": _strategy_info(),
        "alert_tfs": settings.alert_tf_list,
        "tf_status": _tf_status(settings),
        "pipeline": {
            "running": pipeline.get("running"),
            "last_ok": last.get("ok"),
            "last_trigger": last.get("trigger"),
            "last_finished_at": last.get("finished_at"),
            "last_fetch": (last.get("steps") or {}).get("fetch"),
            "last_error": last.get("error"),
        },
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


def _fetch_disabled() -> bool:
    import os

    settings = get_settings()
    if os.environ.get("PA_DISABLE_FETCH", "").lower() in ("1", "true", "yes"):
        return True
    if "pythonanywhere" in os.environ.get("HOME", "").lower() and not settings.enable_scheduler:
        return True
    return not settings.enable_fetch


@app.post("/fetch")
def fetch_endpoint(
    tf: TfParam = Query("H1"),
    group: str | None = Query(None),
    limit: int = Query(500, ge=50, le=5000),
    background: bool = Query(
        True,
        description="true (default): start fetch→scan→refresh in background, return 202. "
        "false: synchronous fetch only (can take 1–3 min for 115 symbols).",
    ),
):
    """Live candle fetch. Disabled (501) on PythonAnywhere free / ENABLE_FETCH=false."""
    if _fetch_disabled():
        raise HTTPException(
            status_code=501,
            detail=(
                "Fetch désactivé (PA free ou ENABLE_FETCH=false). "
                "scripts/fetch_candles.py en local → upload cache → refresh_status.py --tf H1"
            ),
        )
    if background and not group:
        from fastapi.responses import JSONResponse

        from ..core.jobs import is_running, start_pipeline_thread

        if is_running():
            return JSONResponse(
                status_code=409,
                content={"started": False, "detail": "pipeline already running", "status": "/jobs/status"},
            )
        start_pipeline_thread(tfs=[tf], limit=limit, trigger="api")
        return JSONResponse(
            status_code=202, content={"started": True, "tf": tf, "status": "/jobs/status"}
        )
    groups = _strategy_groups_or_400(group)
    summary = fetch_all(tfs=[tf], groups=groups, limit=limit, write=True)
    return {
        "tf": tf,
        "ok": summary.ok_count,
        "fail": summary.fail_count,
        "elapsed_sec": round(summary.elapsed_sec, 2),
        "by_source": summary.by_source(),
    }


@app.get("/jobs/status")
def jobs_status():
    from ..core.jobs import read_status

    return {"pipeline": read_status(), "scheduler": _scheduler_info()}


@app.get("/cache-status")
def cache_status(tf: TfParam = Query("H1")):
    settings = get_settings()
    return cache_freshness(settings.cache_dir, tf)


@app.post("/scan")
def scan_endpoint(
    tf: TfParam = Query("H1"),
    group: str | None = Query(None),
    symbols: str | None = Query(None),
    min_score: int = Query(4, ge=1, le=5),
    include_mitigated: bool = Query(False),
):
    groups = _strategy_groups_or_400(group)
    min_score = get_settings().clamp_min_score(min_score)
    syms = [s.strip() for s in symbols.split(",")] if symbols else None
    summary = run_scan(
        tfs=[tf],
        groups=groups,
        symbols=syms,
        min_score=min_score,
        require_fresh=not include_mitigated,
        persist=True,
    )
    refresh_meta = None
    try:
        rsum = refresh_statuses(
            tf=tf,
            history=False,
            groups=groups,
            min_score=min_score,
            notify=False,
            force_dry_telegram=True,
        )
        refresh_meta = {
            "mode": rsum.mode,
            "updated": rsum.updated,
            "by_status": rsum.by_status,
            "elapsed_sec": round(rsum.elapsed_sec, 2),
        }
    except Exception as e:
        refresh_meta = {"error": str(e)[:300]}
    return {
        "tf": tf,
        "elapsed_sec": round(summary.elapsed_sec, 2),
        "n_zones": len(summary.zones),
        "symbols_scanned": len(summary.per_symbol),
        "symbols_ok": sum(1 for s in summary.per_symbol if s.ok),
        "zones": [z.to_dict() for z in summary.zones],
        "refresh": refresh_meta,
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
        tf=_tf_opt(tf),
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
    tf: TfParam = Query("H1"),
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
    tf: TfParam = Query("H1"),
    history: bool = Query(
        False,
        description="Re-detect including mitigated and classify lifecycle (for Touches/Réaction)",
    ),
    group: str | None = Query(None),
    min_score: int = Query(4, ge=1, le=5),
    notify: bool = Query(True),
    dry_run: bool = Query(True),
):
    groups = _strategy_groups_or_400(group)
    min_score = get_settings().clamp_min_score(min_score)
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
    return compute_stats(tf=_tf_opt(tf))


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

