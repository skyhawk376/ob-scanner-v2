"""
PythonAnywhere WSGI entry for OB Scanner v2 — pure WSGI (no a2wsgi).

a2wsgi hangs under PA's uWSGI even though the same callable works in a console
probe. v1 used a hand-rolled WSGI app; we do the same and call sync business
logic from backend/app directly. Local uvicorn + FastAPI stays unchanged.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONT = ROOT / "frontend" / "dist"

os.environ.setdefault("CACHE_DIR", str(ROOT / "data" / "cache"))
os.environ.setdefault("RESULTS_DIR", str(ROOT / "data" / "results"))
os.environ.setdefault("TZ", "Europe/Paris")
os.environ.setdefault("ENABLE_SCHEDULER", "false")

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

(ROOT / "data" / "cache").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results" / "charts").mkdir(parents=True, exist_ok=True)

from app.core.cache import cache_freshness, read_cache  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.monitor import compute_stats, refresh_statuses  # noqa: E402
from app.core.scanner import load_stored_zones, run_scan  # noqa: E402
from app.core.symbols import count_by_group, load_instruments  # noqa: E402

try:
    get_settings.cache_clear()
except Exception:
    pass


def _json(start_response, status: str, obj, extra=None):
    body = json.dumps(obj, default=str).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
    ]
    if extra:
        headers.extend(extra)
    start_response(status, headers)
    return [body]


def _file(start_response, path: Path):
    if not path.is_file():
        return None
    data = path.read_bytes()
    ctype, _ = mimetypes.guess_type(str(path))
    if not ctype:
        ctype = "application/octet-stream"
    if path.suffix == ".js":
        ctype = "application/javascript; charset=utf-8"
    elif path.suffix == ".css":
        ctype = "text/css; charset=utf-8"
    elif path.suffix == ".html":
        ctype = "text/html; charset=utf-8"
    elif path.suffix == ".svg":
        ctype = "image/svg+xml"
    start_response(
        "200 OK",
        [
            ("Content-Type", ctype),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
            ("Access-Control-Allow-Origin", "*"),
        ],
    )
    return [data]


def _q(qs: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(qs, keep_blank_values=False)


def _one(params: dict, key: str, default: str | None = None) -> str | None:
    vals = params.get(key)
    if not vals:
        return default
    return vals[0]


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _norm_path(path: str) -> str:
    """Strip optional /api prefix so prod and hardcoded /api/symbols both work."""
    if path.startswith("/api/"):
        return path[4:]
    if path == "/api":
        return "/"
    return path


def _handle_api(method: str, path: str, qs: str):
    settings = get_settings()
    params = _q(qs)

    if path == "/health" and method == "GET":
        try:
            instruments = load_instruments(settings.symbols_yaml)
            n = len(instruments)
            by_group = count_by_group(instruments)
        except Exception as e:
            return ("200 OK", {"status": "degraded", "phase": "P5", "error": str(e)})
        cache_info = cache_freshness(settings.cache_dir, "H1")
        return (
            "200 OK",
            {
                "status": "ok",
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
                "wsgi": "pure",
                "scheduler": False,
            },
        )

    if path == "/symbols" and method == "GET":
        instruments = load_instruments(settings.symbols_yaml)
        return (
            "200 OK",
            [
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
            ],
        )

    if path == "/scan" and method == "POST":
        tf = (_one(params, "tf", "H1") or "H1").upper()
        group = _one(params, "group")
        symbols = _one(params, "symbols")
        min_score = int(_one(params, "min_score", "4") or "4")
        include_mitigated = _bool(_one(params, "include_mitigated"), False)
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
        # P0: auto-chain lifecycle refresh so Touches/Réaction are not empty
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
        return (
            "200 OK",
            {
                "tf": tf,
                "elapsed_sec": round(summary.elapsed_sec, 2),
                "n_zones": len(summary.zones),
                "symbols_scanned": len(summary.per_symbol),
                "symbols_ok": sum(1 for s in summary.per_symbol if s.ok),
                "zones": [z.to_dict() for z in summary.zones],
                "refresh": refresh_meta,
            },
        )

    if path == "/zones" and method == "GET":
        tf = _one(params, "tf")
        group = _one(params, "group")
        symbol = _one(params, "symbol")
        status = _one(params, "status")
        statuses = _one(params, "statuses")
        min_score = int(_one(params, "min_score", "4") or "4")
        limit = int(_one(params, "limit", "200") or "200")
        active_only = _bool(_one(params, "active_only"), False)
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
        return ("200 OK", {"n": len(zones), "zones": zones})

    if path.startswith("/candles/") and method == "GET":
        symbol = path.split("/", 2)[2].upper()
        tf = (_one(params, "tf", "H1") or "H1").upper()
        limit = int(_one(params, "limit", "200") or "200")
        df = read_cache(settings.cache_dir, symbol, tf)
        if df is None or df.empty:
            return ("404 Not Found", {"detail": f"No cache for {symbol} {tf}"})
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
        return ("200 OK", {"symbol": symbol, "tf": tf, "n": len(candles), "candles": candles})

    if path == "/refresh" and method == "POST":
        tf = (_one(params, "tf", "H1") or "H1").upper()
        history = _bool(_one(params, "history"), False)
        group = _one(params, "group")
        min_score = int(_one(params, "min_score", "4") or "4")
        dry_run = _bool(_one(params, "dry_run"), True)
        groups = [g.strip() for g in group.split(",")] if group else None
        summary = refresh_statuses(
            tf=tf,
            history=history,
            groups=groups,
            min_score=min_score,
            notify=True,
            force_dry_telegram=dry_run,
        )
        return (
            "200 OK",
            {
                "mode": summary.mode,
                "elapsed_sec": round(summary.elapsed_sec, 2),
                "n_zones": summary.n_zones,
                "updated": summary.updated,
                "by_status": summary.by_status,
                "transitions": len(summary.transitions),
                "notifications": summary.notifications,
            },
        )

    if path == "/stats" and method == "GET":
        tf = _one(params, "tf")
        return ("200 OK", compute_stats(tf=tf))


    if path == "/fetch" and method == "POST":
        # Free PA: no yfinance/ccxt — live fetch would fail or bloat disk.
        # Documented cron path: fetch locally → upload cache → refresh_status.py
        return (
            "501 Not Implemented",
            {
                "ok": False,
                "detail": (
                    "POST /fetch désactivé sur PythonAnywhere free "
                    "(pas de yfinance/ccxt, quota disque). "
                    "Utiliser scripts/fetch_candles.py en local, uploader data/cache/, "
                    "puis scripts/refresh_status.py --tf H1 (et --history pour backfill)."
                ),
                "cron": {
                    "local_fetch": "python scripts/fetch_candles.py --tf H1 --quiet",
                    "upload": "scp/rsync data/cache/ → ~/ob-scanner-v2/data/cache/",
                    "refresh": "cd ~/ob-scanner-v2 && .venv/bin/python scripts/refresh_status.py --tf H1",
                    "history_daily": ".venv/bin/python scripts/refresh_status.py --tf H1 --history",
                },
            },
        )

    if path == "/cache-status" and method == "GET":
        tf_c = (_one(params, "tf", "H1") or "H1").upper()
        info = cache_freshness(settings.cache_dir, tf_c)
        return ("200 OK", info)

    if path == "/mcp/tools" and method == "GET":
        from app.mcp.catalog import TOOL_CATALOG

        venv_py = str(ROOT / ".venv" / "bin" / "python")
        return (
            "200 OK",
            {
                "status": "ready",
                "phase": "P5",
                "transport": ["stdio"],
                "tools": TOOL_CATALOG,
                "note": "MCP stdio en local uniquement — pas sur PythonAnywhere web.",
                "run": {"command": venv_py, "args": ["-m", "app.mcp.server"], "cwd": str(BACKEND)},
            },
        )

    return None


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO") or "/"
    qs = environ.get("QUERY_STRING") or ""

    if method == "OPTIONS":
        start_response(
            "204 No Content",
            [
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type"),
                ("Content-Length", "0"),
            ],
        )
        return [b""]

    api_path = _norm_path(path)
    try:
        handled = _handle_api(method, api_path, qs)
    except Exception as e:
        return _json(
            start_response,
            "500 Internal Server Error",
            {"error": str(e), "trace": traceback.format_exc()[-1500:]},
        )
    if handled is not None:
        status, obj = handled
        return _json(start_response, status, obj)

    # Static frontend (Vite dist)
    if not FRONT.is_dir():
        return _json(start_response, "404 Not Found", {"error": "frontend/dist missing"})

    rel = path.lstrip("/")
    if not rel or rel.endswith("/"):
        rel = "index.html"
    candidate = (FRONT / rel).resolve()
    try:
        candidate.relative_to(FRONT.resolve())
    except ValueError:
        start_response("403 Forbidden", [("Content-Type", "text/plain")])
        return [b"Forbidden"]

    result = _file(start_response, candidate)
    if result is not None:
        return result

    # SPA fallback
    result = _file(start_response, FRONT / "index.html")
    if result is not None:
        return result

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not Found"]


# Local smoke: python3 wsgi.py
if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print(f"pure WSGI smoke → http://127.0.0.1:{port}/")
    with make_server("127.0.0.1", port, application) as httpd:
        httpd.serve_forever()
