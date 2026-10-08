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


def maybe_fetch_d1(
    settings: Settings, group_list: list[str] | None, *, force: bool = False
) -> dict[str, Any] | None:
    """Fetch D1 candles (H4/D1 trend bias, info only) when the D cache is missing or
    older than BIAS_D1_REFRESH_HOURS. Never scanned. Errors never fail the pipeline."""
    if not settings.bias_fetch_d1:
        return None
    mt = _newest_mtime(settings.cache_dir, "D")
    if not force and mt is not None and (time.time() - mt) < settings.bias_d1_refresh_hours * 3600:
        return None
    try:
        from .fetcher import fetch_all

        fs = fetch_all(
            tfs=["D"], groups=group_list, limit=int(settings.bias_d1_limit), write=True, settings=settings
        )
        return {"ok": fs.ok_count, "fail": fs.fail_count, "elapsed_sec": round(fs.elapsed_sec, 1)}
    except Exception as e:  # pragma: no cover
        return {"error": f"{type(e).__name__}: {e}"[:300]}


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


def _tf_has_zones(settings: Settings, tf: str) -> bool:
    """Any stored zone for this TF (H1 on prod → True: it was already alerting)."""
    try:
        from .store import connect

        db = settings.db_path
        if not Path(db).exists():
            return False
        conn = connect(db)
        try:
            row = conn.execute("SELECT 1 FROM zones WHERE tf=? LIMIT 1", (tf.upper(),)).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False  # unknown → warm-up (silent run) rather than risk an alert burst


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
    """Run fetch → scan → refresh per TF (H1 first). Returns a summary; skips if
    already running. Telegram is gated per TF by ALERT_TFS inside notify_zone_event."""
    from .timeframes import by_priority, parse_tf_list

    settings = settings or get_settings()
    if not _LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "pipeline already running", "current": _STATE["current"]}

    tf_list = by_priority(parse_tf_list(tfs)) if tfs else settings.pipeline_tfs
    # None → DEFAULT_SCAN_GROUPS (NQ100 off by default); pass groups="ALL" for full universe
    group_list = settings.clamp_groups(groups)  # Filtre B lock → METAUX,FOREX,CRYPTO
    if group_list is not None and not group_list:
        group_list = settings.strategy_groups
    lim = int(limit or settings.fetch_limit)
    started = time.time()
    min_score = settings.clamp_min_score(int(settings.default_min_score))
    summary: dict[str, Any] = {
        "trigger": trigger,
        "started_at": _now_iso(),
        "tfs": tf_list,
        "groups": group_list if group_list is not None else "ALL",
        "min_score": min_score,
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
        runs_before = read_tf_runs(settings)
        for tf in tf_list:
            t_tf = time.time()
            rec: dict[str, Any] = {"last_run": _now_iso(), "last_run_ts": t_tf, "trigger": trigger}
            prev = runs_before.get(tf) or {}
            # Go-live warm-up: first live run of a TF that has no zones yet → lifecycle
            # recorded silently, alerts armed only for touches after this run.
            warmup = bool(notify and not history and not prev and not _tf_has_zones(settings, tf))
            armed_at = prev.get("armed_at_ts")
            if fetch:
                if not settings.enable_fetch:
                    summary["steps"]["fetch"] = {"skipped": "ENABLE_FETCH=false"}
                else:
                    from .fetcher import fetch_all

                    tf_lim = _tf_limit(settings, tf, limit)
                    fs = fetch_all(tfs=[tf], groups=group_list, limit=tf_lim, write=True, settings=settings)
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
            if scan:
                from .scanner import run_scan

                ss = run_scan(
                    tfs=[tf],
                    groups=group_list,
                    persist=True,
                    min_score=min_score,
                    settings=settings,
                )
                summary["steps"][f"scan_{tf}"] = {
                    "zones": len(ss.zones),
                    "symbols_ok": sum(1 for s in ss.per_symbol if s.ok),
                    "min_score": min_score,
                    "elapsed_sec": round(ss.elapsed_sec, 1),
                }
                rec["zones"] = len(ss.zones)
            if refresh:
                from .monitor import refresh_statuses

                rs = refresh_statuses(
                    tf=tf,
                    history=history,
                    groups=group_list,
                    min_score=min_score,
                    notify=notify and not warmup,
                    force_dry_telegram=None,  # honour TELEGRAM_DRY_RUN
                    settings=settings,
                    notify_since=armed_at,
                )
                summary["steps"][f"refresh_{tf}"] = {
                    "mode": rs.mode,
                    "updated": rs.updated,
                    "by_status": rs.by_status,
                    "notifications": rs.notifications,
                    "alerts_enabled": settings.tf_alerts_enabled(tf),
                    "warmup_silent": warmup,
                    # active zones missing from this scan, resolved before any prune
                    "vanished": {
                        "touched": getattr(rs, "vanished_touched", 0),
                        "expired": getattr(rs, "vanished_expired", 0),
                        "pruned": getattr(rs, "vanished_pruned", 0),
                    },
                    "stale_alerts_skipped": getattr(rs, "stale_skipped", 0),
                    "elapsed_sec": round(rs.elapsed_sec, 1),
                }
            if warmup:
                armed_at = time.time()
            if armed_at is not None:
                rec["armed_at_ts"] = armed_at
                rec["armed_at"] = datetime.fromtimestamp(armed_at, timezone.utc).isoformat(timespec="seconds")
            rec.update(ok=True, elapsed_sec=round(time.time() - t_tf, 1))
            if fetch and not history:
                _write_tf_run(settings, tf, rec)
        if did_fetch:
            summary["steps"]["fetch"] = agg
        if fetch and settings.enable_fetch and "D" not in settings.pipeline_tfs:
            # D not scanned on this host → still keep D1 candles for the H4/D1 bias
            d1 = maybe_fetch_d1(settings, group_list)
            if d1 is not None:
                summary["steps"]["fetch_d1_bias"] = d1
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
        f"[pipeline] {trigger} tfs={','.join(tf_list)} ok={summary['ok']} {summary['elapsed_sec']}s "
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
