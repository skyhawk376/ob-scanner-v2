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


def _newest_mtime(cache_dir: Path, tf: str) -> float | None:
    files = list(Path(cache_dir).glob(f"*_{tf}.parquet")) + list(Path(cache_dir).glob(f"*_{tf}.pkl"))
    if not files:
        return None
    return max(f.stat().st_mtime for f in files)


def _tf_runs_path(settings: Settings) -> Path:
    return Path(settings.results_dir) / "tf_runs.json"


def read_tf_runs(settings: Settings | None = None) -> dict[str, Any]:
    """Per-TF last pipeline run ({tf: {last_run, ok, zones, fetch_ok, ...}})."""
    settings = settings or get_settings()
    path = _tf_runs_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_tf_run(settings: Settings, tf: str, rec: dict[str, Any]) -> None:
    try:
        data = read_tf_runs(settings)
        data[tf] = rec
        path = _tf_runs_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:  # pragma: no cover
        print(f"[pipeline] could not write tf_runs: {e}", flush=True)


def due_tfs(settings: Settings | None = None, now: float | None = None) -> list[str]:
    """TFs whose cadence (TF_SCHEDULE) has elapsed since their last run, H1 first.

    A small slack (≤ 90 s, ≤ 20 % of the cadence) absorbs scheduler tick jitter so a
    15-min TF runs on every 3rd 5-min tick.
    """
    settings = settings or get_settings()
    now = time.time() if now is None else now
    runs = read_tf_runs(settings)
    cad = settings.tf_cadence
    out: list[str] = []
    for tf in settings.pipeline_tfs:
        minutes = cad.get(tf, 15)
        last = (runs.get(tf) or {}).get("last_run_ts")
        slack = min(90.0, 0.2 * minutes * 60)
        if last is None or (now - float(last)) >= minutes * 60 - slack:
            out.append(tf)
    return out


def run_due(trigger: str = "schedule", settings: Settings | None = None) -> dict[str, Any]:
    """Scheduler tick: run the pipeline for the TFs that are due (no-op if none)."""
    settings = settings or get_settings()
    tfs = due_tfs(settings)
    if not tfs:
        return {"skipped": True, "reason": "no TF due"}
    return run_pipeline(tfs=tfs, trigger=trigger, settings=settings)


def _tf_limit(settings: Settings, tf: str, limit: int | None) -> int:
    """Explicit limit wins; else bootstrap depth when the TF cache is empty."""
    if limit:
        return int(limit)
    mt = _newest_mtime(settings.cache_dir, tf)
    return int(settings.bootstrap_limit if mt is None else settings.fetch_limit)


def run_pipeline(
    *,
    tfs: list[str] | None = None,
    groups: list[str] | str | None = None,
    limit: int | None = None,
    fetch: bool = True,
    scan: bool = True,
    refresh: bool = True,
    history: bool = False,
    notify: bool = True,
    trigger: str = "manual",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """v3 pipeline per TF (H1 first): fetch candles → v3 refresh (detect → simulate →
    persist → Telegram), then track every open zone/trade of the other TFs on their
    lower TF. Telegram gated by ALERT_TFS + per-TF go-live arming (v3_meta)."""
    from ..v3.service import refresh_tf, track_open, universe
    from .timeframes import by_priority, parse_tf_list

    settings = settings or get_settings()
    if not _LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "pipeline already running", "current": _STATE["current"]}

    tf_list = by_priority(parse_tf_list(tfs)) if tfs else settings.pipeline_tfs
    lim = int(limit or settings.fetch_limit)
    started = time.time()
    syms = [i.id for i in universe(settings)]
    if groups:
        gl = settings.resolved_scan_groups(groups)
        if gl:
            syms = [i.id for i in universe(settings) if i.group in gl]
    summary: dict[str, Any] = {
        "engine": "v3",
        "trigger": trigger,
        "started_at": _now_iso(),
        "tfs": tf_list,
        "groups": settings.v3_group_list,
        "n_symbols": len(syms),
        "limit": lim,
        "alert_tfs": settings.alert_tf_list,
        "steps": {},
        "ok": False,
    }
    _STATE["running"] = True
    _STATE["current"] = {"trigger": trigger, "started_at": summary["started_at"], "tfs": tf_list}
    agg: dict[str, Any] = {"ok": 0, "fail": 0, "elapsed_sec": 0.0, "by_source": {}, "failures": []}
    did_fetch = False
    try:
        for tf in tf_list:
            t_tf = time.time()
            rec: dict[str, Any] = {"last_run": _now_iso(), "last_run_ts": t_tf, "trigger": trigger}
            if fetch:
                if not settings.enable_fetch:
                    summary["steps"]["fetch"] = {"skipped": "ENABLE_FETCH=false"}
                else:
                    from .fetcher import fetch_all

                    tf_lim = _tf_limit(settings, tf, limit)
                    fs = fetch_all(tfs=[tf], symbols=syms, limit=tf_lim, write=True, settings=settings)
                    did_fetch = True
                    fails = [
                        f"{r.symbol} {r.tf} {r.source}: {(r.error or '')[:120]}"
                        for r in fs.results
                        if not r.ok
                    ]
                    by_src = fs.by_source()
                    summary["steps"][f"fetch_{tf}"] = {
                        "ok": fs.ok_count,
                        "fail": fs.fail_count,
                        "limit": tf_lim,
                        "elapsed_sec": round(fs.elapsed_sec, 1),
                        "by_source": by_src,
                        "failures": fails[:10],
                    }
                    agg["ok"] += fs.ok_count
                    agg["fail"] += fs.fail_count
                    agg["elapsed_sec"] = round(agg["elapsed_sec"] + fs.elapsed_sec, 1)
                    for src, b in by_src.items():
                        a = agg["by_source"].setdefault(src, {"ok": 0, "fail": 0})
                        a["ok"] += b.get("ok", 0)
                        a["fail"] += b.get("fail", 0)
                    agg["failures"] = (agg["failures"] + fails)[:20]
                    rec.update(fetch_ok=fs.ok_count, fetch_fail=fs.fail_count)
            if scan or refresh:
                rs = refresh_tf(tf, settings=settings, notify=notify and not history,
                                symbols=syms)
                summary["steps"][f"v3_{tf}"] = rs
                rec["zones"] = rs["zones"]
                rec["zones_by_group"] = rs["by_group"]
                if rs.get("errors"):
                    rec["errors"] = rs["errors"][:3]
            rec.update(ok=True, elapsed_sec=round(time.time() - t_tf, 1))
            if fetch and not history:
                _write_tf_run(settings, tf, rec)
        if refresh and not history:
            summary["steps"]["track_open"] = track_open(settings=settings, skip_tfs=tf_list, notify=notify)
        if did_fetch:
            summary["steps"]["fetch"] = agg
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
        f"[pipeline] v3 {trigger} tfs={','.join(tf_list)} ok={summary['ok']} {summary['elapsed_sec']}s "
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
