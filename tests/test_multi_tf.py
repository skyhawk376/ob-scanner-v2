"""Multi-TF scanner (M5 … W): TF parsing, cadence, providers, clamp, alert TF gating,
go-live warm-up (no burst at deploy), stats by TF."""
from __future__ import annotations

import time

import pandas as pd
import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_DRY_RUN", "true")
    monkeypatch.setenv("FETCH_TFS", "M5,M15,M30,H1,H4,D,W")
    monkeypatch.delenv("ALERT_TFS", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _zone(tf="M15", symbol="EURUSD", score=4, zid=None):
    return {
        "id": zid or f"{symbol}|{tf}|bull|2026-10-05T10:00:00+00:00",
        "symbol": symbol,
        "tf": tf,
        "direction": "bull",
        "score": score,
        "low": 1.10,
        "high": 1.11,
        "entry": 1.105,
        "sl": 1.095,
        "tp1": 1.12,
        "entry_mode": "mid",
    }


# ---------------- TF parsing / cadence ----------------

def test_normalize_and_parse_tfs():
    from app.core.timeframes import normalize_tf, parse_tf_list

    assert normalize_tf("daily") == "D" and normalize_tf("W1") == "W" and normalize_tf("15m") == "M15"
    assert normalize_tf("4h") == "H4" and normalize_tf("nope") is None and normalize_tf("") is None
    assert parse_tf_list("M5,m15,M30,H1,H4,D1,W1,M5,bogus") == ["M5", "M15", "M30", "H1", "H4", "D", "W"]


def test_schedule_defaults_and_priority(env):
    from app.core.config import get_settings

    s = get_settings()
    assert s.pipeline_tfs[0] == "H1"  # H1 processed first → no latency regression
    assert set(s.pipeline_tfs) == {"M5", "M15", "M30", "H1", "H4", "D", "W"}
    cad = s.tf_cadence
    assert cad["M5"] == 5 and cad["M15"] == 15 and cad["H1"] == 15 and cad["M30"] == 30
    assert cad["H4"] == 60 and cad["D"] == 120 and cad["W"] == 360


def test_parse_schedule_minimum_and_fallback():
    from app.core.timeframes import parse_schedule

    sch = parse_schedule("M5:1,H1:15", ["M5", "H1", "D"])
    assert sch["M5"] == 5  # clamped to ≥ 5 min
    assert sch["H1"] == 15 and sch["D"] == 360  # missing → TF minutes capped at 6 h


def test_due_tfs_respects_cadence(env):
    from app.core import jobs
    from app.core.config import get_settings

    s = get_settings()
    now = time.time()
    assert jobs.due_tfs(s, now=now)[0] == "H1"  # nothing ran yet → everything due
    for tf in s.pipeline_tfs:
        jobs._write_tf_run(s, tf, {"last_run_ts": now - 5 * 60})
    due = jobs.due_tfs(s, now=now)
    assert due == ["M5"]
    for tf in s.pipeline_tfs:
        jobs._write_tf_run(s, tf, {"last_run_ts": now - 15 * 60 + 30})  # tick jitter
    assert jobs.due_tfs(s, now=now) == ["H1", "M5", "M15"]


# ---------------- providers / engine ----------------

def test_providers_support_low_tfs():
    from app.providers.binance_provider import TF_BINANCE
    from app.providers.oanda_provider import TF_OANDA
    from app.providers.yfinance_provider import TF_YF, _period_for

    for tf, iv in (("M5", "5m"), ("M15", "15m"), ("M30", "30m")):
        assert TF_BINANCE[tf] == iv and TF_YF[tf]["interval"] == iv and TF_OANDA[tf] == tf
    assert _period_for(TF_YF["M5"], 300) == "5d"
    assert _period_for(TF_YF["M5"], 100000) == "59d"  # Yahoo 60-day intraday cap
    assert _period_for(TF_YF["H1"], 300) == "60d"  # H1 never below 60 days
    assert _period_for(TF_YF["D"], 300) == "max"


def test_low_tf_params_like_h1():
    from app.engine.params import params_for_tf

    for tf in ("M5", "M15", "M30"):
        p = params_for_tf(tf)
        assert p.pivot_n == 3 and p.lookback == 500
        assert tf not in p.session_at_touch_tfs  # ★5 at formation, like H1


def test_detect_zones_tags_tf():
    import numpy as np

    from app.engine.detect import detect_zones

    rng = np.random.default_rng(0)
    n = 600
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    idx = pd.date_range("2026-09-01", periods=n, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": close, "high": close + 0.3, "low": close - 0.3, "close": close}, index=idx)
    zones = detect_zones(df, symbol="EURUSD", tf="M5", min_score=1, require_fresh=False)
    assert all(z.tf == "M5" and "|M5|" in z.id for z in zones)


def test_merge_cache_max_bars(tmp_path):
    from app.core.cache import merge_cache, read_cache

    idx = pd.date_range("2026-10-01", periods=50, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 0.0}, index=idx)
    merge_cache(tmp_path, "EURUSD", "M5", df, max_bars=20)
    out = read_cache(tmp_path, "EURUSD", "M5")
    assert len(out) == 20 and out.index[-1] == idx[-1]


def test_cache_max_bars_setting(env):
    from app.core.config import get_settings

    s = get_settings()
    assert s.cache_max_bars_for("M5") == 6000 and s.cache_max_bars_for("H1") == 0


# ---------------- clamp + alert gating ----------------

def test_alert_tfs_default_all_and_narrowable(env):
    from app.core.config import get_settings

    s = get_settings()
    assert s.alert_tf_list == ["M5", "M15", "M30", "H1", "H4", "D", "W"]
    env.setenv("ALERT_TFS", "H1")
    get_settings.cache_clear()
    s = get_settings()
    assert s.tf_alerts_enabled("H1") and not s.tf_alerts_enabled("M5") and not s.tf_alerts_enabled("D")
    env.setenv("ALERT_TFS", "M5,M15,M30,H1,H4,D1,W1")  # D1/W1 aliases from the Fly env
    get_settings.cache_clear()
    assert get_settings().alert_tf_list == ["M5", "M15", "M30", "H1", "H4", "D", "W"]


def test_notify_gated_by_alert_tfs(env):
    from app.core import telegram as tg
    from app.core.config import get_settings

    sends = []
    env.setattr(tg, "send_telegram", lambda text, **kw: sends.append(text) or {"ok": True})
    env.setenv("ALERT_TFS", "H1")
    get_settings.cache_clear()
    r = tg.notify_zone_event("touchee", _zone("M15"), force_dry=True)
    assert r == {"ok": True, "skipped": "tf_not_alerted"} and not sends
    r = tg.notify_zone_event("touchee", _zone("H1"), force_dry=True)
    assert r and not r.get("skipped") and len(sends) == 1


def test_notify_all_tfs_keeps_filtre_b_rules(env):
    from app.core import telegram as tg

    sends = []
    env.setattr(tg, "send_telegram", lambda text, **kw: sends.append(text) or {"ok": True})
    for tf in ("M5", "M15", "M30", "H1", "H4", "D", "W"):
        r = tg.notify_zone_event("touchee", _zone(tf), force_dry=True)
        assert r and not r.get("skipped"), tf
    assert len(sends) == 7
    # anti-doublon still per zone/event
    assert tg.notify_zone_event("touchee", _zone("M5"), force_dry=True)["skipped"] == "duplicate"
    # ≥4★ and groups clamp still apply on every TF
    assert tg.notify_zone_event("touchee", _zone("M5", score=3, zid="a"), force_dry=True) is None
    r = tg.notify_zone_event("touchee", _zone("M5", symbol="AAPL", zid="b"), force_dry=True)
    assert r["skipped"] == "outside_strategy"
    assert len(sends) == 7


def test_message_shows_tf_clearly():
    from app.core.telegram import format_zone_message, tf_label

    assert tf_label("D") == "D1" and tf_label("W") == "W1" and tf_label("M15") == "M15"
    msg = format_zone_message("touchee", _zone("M15"))
    first, second = msg.splitlines()[:2]
    assert first.endswith("· M15") and second == "ZONE ACHAT EURUSD M15"
    assert "ZONE ACHAT EURUSD D1" in format_zone_message("touchee", _zone("D"))


# ---------------- go-live warm-up (no burst) ----------------

def test_touched_since_guard():
    from app.core.monitor import _touched_since

    t0 = pd.Timestamp("2026-10-06T12:00:00Z").timestamp()
    assert _touched_since("2026-10-06T11:55:00+00:00", None) is True
    assert _touched_since("2026-10-06T11:55:00+00:00", t0) is False
    assert _touched_since("2026-10-06T12:05:00+00:00", t0) is True
    assert _touched_since(None, t0) is False


def test_first_run_of_new_tf_is_silent_then_armed(env):
    import app.core.fetcher as fetcher
    import app.core.monitor as monitor
    import app.core.scanner as scanner
    from app.core import jobs
    from app.core.config import get_settings

    class _FS:
        ok_count, fail_count, elapsed_sec, results = 1, 0, 0.1, []

        def by_source(self):
            return {"test": {"ok": 1, "fail": 0}}

    class _SS:
        zones, per_symbol, elapsed_sec = [], [], 0.0

    class _RS:
        mode, updated, by_status, notifications, elapsed_sec = "refresh", 0, {}, 0, 0.0

    calls = []
    env.setattr(fetcher, "fetch_all", lambda **kw: _FS())
    env.setattr(scanner, "run_scan", lambda **kw: _SS())
    env.setattr(monitor, "refresh_statuses", lambda **kw: calls.append(kw) or _RS())
    s = get_settings()
    out = jobs.run_pipeline(tfs=["M5"], trigger="t", settings=s)
    assert out["ok"] and out["steps"]["refresh_M5"]["warmup_silent"] is True
    assert calls[-1]["notify"] is False
    armed = jobs.read_tf_runs(s)["M5"]["armed_at_ts"]
    assert armed
    out = jobs.run_pipeline(tfs=["M5"], trigger="t", settings=s)
    assert out["steps"]["refresh_M5"]["warmup_silent"] is False
    assert calls[-1]["notify"] is True and calls[-1]["notify_since"] == armed


def test_tf_with_existing_zones_is_not_warmed_up(env):
    """H1 on prod already has zones (and was alerting) → no silent run, no guard."""
    import app.core.fetcher as fetcher
    import app.core.monitor as monitor
    import app.core.scanner as scanner
    from app.core import jobs
    from app.core.config import get_settings
    from app.core.store import connect, upsert_zones

    s = get_settings()
    s.results_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(s.db_path)
    z = {**_zone("H1"), "ts_ob": "2026-10-05T10:00:00+00:00", "ts_bos": "2026-10-05T12:00:00+00:00",
         "fresh": True, "star3_fib": True, "distance_atr": 1.0}
    try:
        upsert_zones(conn, [z], tf="H1", symbols={"EURUSD"})
        conn.commit()
    except Exception:
        conn.execute(
            "INSERT INTO zones (id, symbol, tf, direction, ts_ob, low, high, score, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (z["id"], "EURUSD", "H1", "bull", z["ts_ob"], 1.1, 1.11, 4, "{}"),
        )
        conn.commit()
    conn.close()
    assert jobs._tf_has_zones(s, "H1") is True

    class _FS:
        ok_count, fail_count, elapsed_sec, results = 1, 0, 0.1, []

        def by_source(self):
            return {}

    class _SS:
        zones, per_symbol, elapsed_sec = [], [], 0.0

    class _RS:
        mode, updated, by_status, notifications, elapsed_sec = "refresh", 0, {}, 0, 0.0

    calls = []
    env.setattr(fetcher, "fetch_all", lambda **kw: _FS())
    env.setattr(scanner, "run_scan", lambda **kw: _SS())
    env.setattr(monitor, "refresh_statuses", lambda **kw: calls.append(kw) or _RS())
    jobs.run_pipeline(tfs=["H1"], trigger="t", settings=s)
    assert calls[-1]["notify"] is True and calls[-1]["notify_since"] is None


# ---------------- stats / API ----------------

def test_realistic_stats_by_tf():
    from app.core.monitor import realistic_stats

    base = {"status": "reaction", "touched_at": "2026-09-01T10:00:00+00:00", "symbol": "EURUSD"}
    zones = [
        {**base, "tf": "H1", "trade_status": "closed", "trade_r": 2.0, "trade_exit": "tp"},
        {**base, "tf": "M5", "trade_status": "closed", "trade_r": -1.0, "trade_exit": "sl"},
        {**base, "tf": "M5", "status": "touchee", "trade_status": "unfilled"},
    ]
    s = realistic_stats(zones, gmap={"EURUSD": "FOREX"}, now="2026-09-15T10:00:00+00:00")
    assert list(s["by_tf"]) == ["M5", "H1"]
    assert s["by_tf"]["M5"]["n"] == 1 and s["by_tf"]["M5"]["n_touched"] == 2
    assert s["by_tf"]["M5"]["n_unfilled"] == 1 and s["by_tf"]["H1"]["avg_r"] == 2.0


def test_api_tf_aliases_and_strategy(env):
    from fastapi.testclient import TestClient

    env.setenv("ENABLE_SCHEDULER", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.api.main import app

    with TestClient(app) as c:
        assert c.get("/zones?tf=Daily").status_code == 200
        assert c.get("/zones?tf=M5").status_code == 200
        assert c.get("/zones?tf=bogus").status_code == 400
        assert c.get("/cache-status?tf=M15").status_code == 200
        st = c.get("/strategy").json()
        assert st["alert_tfs"] == ["M5", "M15", "M30", "H1", "H4", "D", "W"]
        assert st["tfs"][0] == "H1" and len(st["tfs"]) == 7
        h = c.get("/health").json()
        assert set(h["tf_status"]) == {"M5", "M15", "M30", "H1", "H4", "D", "W"}
