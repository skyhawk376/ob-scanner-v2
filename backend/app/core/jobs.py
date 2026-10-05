"""Live pipeline for always-on hosts: fetch candles → scan → lifecycle refresh.

One pipeline at a time (process-wide lock). Status is persisted as JSON under
RESULTS_DIR so /health and /jobs/status survive restarts.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, get_settings

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"running": False, "current": None}


def _status_path(settings: Settings) -> Path:
    return Path(settings.results_dir) / "pipeline_status.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    out: dict[str, Any] = {"running": _STATE["running"], "current": _STATE["current"]}
    path = _status_path(settings)
    if path.exists():
        try:
            out["last"] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # corrupted file should never break /health
            out["last"] = {"error": f"unreadable status: {e}"}
    else:
        out["last"] = None
    return out


def _write_status(settings: Settings, payload: dict[str, Any]) -> None:
    path = _status_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def is_running() -> bool:
    return bool(_STATE["running"])


def run_pipeline(
    *,
    tfs: list[str] | None = None,
    limit: int | None = None,
    fetch: bool = True,
    scan: bool = True,
    refresh: bool = True,
    history: bool = False,
    notify: bool = True,
    trigger: str = "manual",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run fetch → scan → refresh. Returns a summary; skips if already running."""
    settings = settings or get_settings()
    if not _LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "pipeline already running", "current": _STATE["current"]}

    tf_list = [t.strip().upper() for t in (tfs or settings.fetch_tfs.split(",")) if t.strip()]
    lim = int(limit or settings.fetch_limit)
    started = time.time()
    summary: dict[str, Any] = {
        "trigger": trigger,
        "started_at": _now_iso(),
        "tfs": tf_list,
        "limit": lim,
        "steps": {},
        "ok": False,
    }
    _STATE["running"] = True
    _STATE["current"] = {"trigger": trigger, "started_at": summary["started_at"], "tfs": tf_list}
    try:
        if fetch:
            if not settings.enable_fetch:
                summary["steps"]["fetch"] = {"skipped": "ENABLE_FETCH=false"}
            else:
                from .fetcher import fetch_all

                fs = fetch_all(tfs=tf_list, limit=lim, write=True, settings=settings)
                summary["steps"]["fetch"] = {
                    "ok": fs.ok_count,
                    "fail": fs.fail_count,
                    "elapsed_sec": round(fs.elapsed_sec, 1),
                    "by_source": fs.by_source(),
                    "failures": [
                        f"{r.symbol} {r.tf} {r.source}: {(r.error or '')[:120]}"
                        for r in fs.results
                        if not r.ok
                    ][:20],
                }
        for tf in tf_list:
            if scan:
                from .scanner import run_scan

                ss = run_scan(tfs=[tf], persist=True, settings=settings)
                summary["steps"][f"scan_{tf}"] = {
                    "zones": len(ss.zones),
                    "symbols_ok": sum(1 for s in ss.per_symbol if s.ok),
                    "elapsed_sec": round(ss.elapsed_sec, 1),
                }
            if refresh:
                from .monitor import refresh_statuses

                rs = refresh_statuses(
                    tf=tf,
                    history=history,
                    notify=notify,
                    force_dry_telegram=None,  # honour TELEGRAM_DRY_RUN
                    settings=settings,
                )
                summary["steps"][f"refresh_{tf}"] = {
                    "mode": rs.mode,
                    "updated": rs.updated,
                    "by_status": rs.by_status,
                    "notifications": rs.notifications,
                    "elapsed_sec": round(rs.elapsed_sec, 1),
                }
        summary["ok"] = True
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"[:500]
        summary["traceback"] = traceback.format_exc()[-2000:]
        print(f"[pipeline] FAILED ({trigger}): {summary['error']}", flush=True)
    finally:
        summary["finished_at"] = _now_iso()
        summary["elapsed_sec"] = round(time.time() - started, 1)
        try:
            _write_status(settings, summary)
        except Exception as e:
            print(f"[pipeline] could not write status: {e}", flush=True)
        _STATE["running"] = False
        _STATE["current"] = None
        _LOCK.release()
    print(
        f"[pipeline] {trigger} ok={summary['ok']} {summary['elapsed_sec']}s "
        f"fetch={summary['steps'].get('fetch', {}).get('ok')}",
        flush=True,
    )
    return summary


def start_pipeline_thread(**kwargs: Any) -> bool:
    """Fire-and-forget pipeline. Returns False if one is already running."""
    if is_running():
        return False
    t = threading.Thread(target=run_pipeline, kwargs=kwargs, name="ob-pipeline", daemon=True)
    t.start()
    return True
