"""TP +2R, H4/D1 bias (info only) and realistic live trade stats."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.cache import write_cache
from app.core.trade_sim import simulate_trade, trade_summary
from app.core.trend_bias import aligned_h4d1, bias_line, compute_bias, ema_bias_at

NOW = pd.Timestamp("2026-10-06 12:00", tz="UTC")


def _h1(rows, start="2026-10-05 00:00"):
    idx = pd.date_range(start=start, periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def _flat(n, p=110.0):
    return [(p, p + 0.5, p - 0.5, p)] * n


BULL = {"direction": "bull", "entry": 100.0, "sl": 90.0, "low": 90.0, "high": 110.0}


# --------------------------------------------------------------------- trade sim
def test_unfilled_when_mid_never_reached():
    rows = _flat(2) + [(110, 111, 105, 108)] + _flat(30)  # touch at 105, entry 100 never hit
    df = _h1(rows)
    z = {**BULL, "touched_at": df.index[2].isoformat()}
    t = simulate_trade(df, z, tp_r=2.0, now=df.index[-1] + pd.Timedelta(hours=1))
    assert t["trade_status"] == "unfilled"
    assert t["trade_r"] is None


def test_pending_within_fill_cap():
    rows = _flat(2) + [(110, 111, 105, 108)] + _flat(3)
    df = _h1(rows)
    z = {**BULL, "touched_at": df.index[2].isoformat()}
    t = simulate_trade(df, z, tp_r=2.0, now=df.index[-1] + pd.Timedelta(hours=1))
    assert t["trade_status"] == "pending"


def test_tp_on_fill_bar_requires_close_beyond():
    # fill bar: low 99 (fill), high 125 (> TP 120) but close 105 → time stop +0.5R
    rows = _flat(2) + [(110, 125, 99, 105)] + _flat(3)
    df = _h1(rows)
    z = {**BULL, "touched_at": df.index[2].isoformat()}
    t = simulate_trade(df, z, tp_r=2.0, now=NOW)
    assert t["trade_status"] == "closed"
    assert t["trade_exit"] == "time"
    assert t["trade_r"] == pytest.approx(0.5)
    # same bar closing above TP → TP +2R
    rows2 = _flat(2) + [(110, 125, 99, 121)] + _flat(3)
    df2 = _h1(rows2)
    t2 = simulate_trade(df2, {**BULL, "touched_at": df2.index[2].isoformat()}, tp_r=2.0, now=NOW)
    assert (t2["trade_exit"], t2["trade_r"]) == ("tp", 2.0)
    assert t2["trade_tp"] == pytest.approx(120.0)


def test_sl_first_when_both_in_same_bar():
    rows = _flat(2) + [(110, 125, 89, 121)] + _flat(3)
    df = _h1(rows)
    t = simulate_trade(df, {**BULL, "touched_at": df.index[2].isoformat()}, tp_r=2.0, now=NOW)
    assert (t["trade_exit"], t["trade_r"]) == ("sl", -1.0)


def test_fill_after_touch_and_bar_in_progress_is_open():
    rows = _flat(2) + [(110, 111, 105, 108), (108, 109, 99.5, 101)]
    df = _h1(rows)
    z = {**BULL, "touched_at": df.index[2].isoformat()}
    # last bar (fill) not closed yet at `now`
    t = simulate_trade(df, z, tp_r=2.0, now=df.index[-1] + pd.Timedelta(minutes=30))
    assert t["trade_status"] == "pending"  # in-progress bar ignored
    t = simulate_trade(df, z, tp_r=2.0, now=df.index[-1] + pd.Timedelta(hours=1))
    assert t["trade_status"] == "closed" and t["trade_exit"] == "time"
    assert t["trade_r"] == pytest.approx(0.1)
    assert t["trade_fill_at"] == df.index[3].isoformat()


def test_m15_path_tp_after_fill():
    rows = _flat(2) + [(110, 125, 99, 115)] + _flat(3)
    df = _h1(rows)
    t0 = df.index[2]
    m = pd.DataFrame(
        [(110, 110, 99.5, 101), (101, 112, 100, 111), (111, 121, 110, 119), (119, 119, 114, 115)],
        index=pd.date_range(t0, periods=4, freq="15min"), columns=["open", "high", "low", "close"],
    )
    # pad M15 to cover the cap window
    pad_idx = pd.date_range(t0 + pd.Timedelta(hours=1), periods=120, freq="15min")
    m = pd.concat([m, pd.DataFrame([(115, 115.5, 114.5, 115)] * 120, index=pad_idx, columns=m.columns)])
    t = simulate_trade(df, {**BULL, "touched_at": t0.isoformat()}, tp_r=2.0, m15=m, now=NOW + pd.Timedelta(days=2))
    assert t["trade_model"] == "m15"
    assert (t["trade_exit"], t["trade_r"]) == ("tp", 2.0)


def test_trade_summary():
    s = trade_summary([
        {"trade_status": "closed", "trade_r": 2.0, "trade_exit": "tp"},
        {"trade_status": "closed", "trade_r": -1.0, "trade_exit": "sl"},
        {"trade_status": "unfilled"},
    ])
    assert s["n"] == 2 and s["wr"] == 0.5 and s["avg_r"] == 0.5


# --------------------------------------------------------------------- bias
def test_ema_bias_uses_closed_bars_only():
    idx = pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC")
    close = np.r_[np.linspace(100, 130, 59), 50.0]  # last bar would flip the bias
    T_mid = idx[-1] + pd.Timedelta(hours=2)  # last bar still open
    assert ema_bias_at(idx, close, pd.Timedelta(hours=4), T_mid, pd.Timedelta(days=4)) == 1
    T_end = idx[-1] + pd.Timedelta(hours=4)
    assert ema_bias_at(idx, close, pd.Timedelta(hours=4), T_end, pd.Timedelta(days=4)) == -1
    # not enough warm-up → None
    assert ema_bias_at(idx[:30], close[:30], pd.Timedelta(hours=4), T_end, pd.Timedelta(days=4)) is None


def test_compute_bias_h4_from_h1_and_d1_missing(tmp_path):
    n = 400
    idx = pd.date_range("2026-09-01", periods=n, freq="1h", tz="UTC")
    c = np.linspace(100, 140, n)
    h1 = pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c}, index=idx)
    write_cache(tmp_path, "EURUSD", "H1", h1)
    T = idx[-1] + pd.Timedelta(hours=1)
    b = compute_bias("EURUSD", "bull", T, cache_dir=tmp_path)
    assert b["bias_h4"] == 1
    assert b["bias_d1"] is None  # ~17 UTC days < EMA50 warm-up → "?"
    assert b["aligned_h4d1"] is None
    assert "D1 ?" in bias_line({"direction": "bull", **b})
    # native D cache → D1 known
    didx = pd.date_range("2026-04-01", periods=170, freq="1D", tz="UTC")
    dc = np.linspace(80, 139, 170)
    write_cache(tmp_path, "EURUSD", "D", pd.DataFrame({"open": dc, "high": dc, "low": dc, "close": dc}, index=didx))
    b2 = compute_bias("EURUSD", "bull", T, cache_dir=tmp_path)
    assert b2["bias_d1"] == 1 and b2["aligned_h4d1"] is True
    assert "✅ aligné H4+D1" in bias_line({"direction": "bull", **b2})
    b3 = compute_bias("EURUSD", "bear", T, cache_dir=tmp_path)
    assert b3["aligned_h4d1"] is False
    assert "⚠️ contre-tendance" in bias_line({"direction": "bear", **b3})


def test_compute_bias_never_raises_without_cache(tmp_path):
    b = compute_bias("NOPE", "bull", NOW, cache_dir=tmp_path)
    assert b["bias_h4"] is None and b["bias_d1"] is None and b["aligned_h4d1"] is None


def test_aligned_logic():
    assert aligned_h4d1("bull", 1, 1) is True
    assert aligned_h4d1("bear", -1, -1) is True
    assert aligned_h4d1("bull", 1, -1) is False
    assert aligned_h4d1("bull", -1, None) is False
    assert aligned_h4d1("bull", 1, None) is None


# --------------------------------------------------------------------- telegram
def test_touch_message_has_bias_line_and_tp2r(monkeypatch):
    monkeypatch.setenv("REACTION_R", "2.0")
    from app.core.telegram import format_zone_message

    z = {
        "id": "x", "symbol": "XAUUSD", "tf": "H1", "direction": "bull", "score": 5,
        "low": 90.0, "high": 110.0, "entry": 100.0, "sl": 90.0, "entry_mode": "mid",
        "touched_session": "London", "bias_h4": 1, "bias_d1": 1, "aligned_h4d1": True,
    }
    msg = format_zone_message("touchee", z)
    assert "TP(+2R) 120 (RR 2.0)" in msg
    assert "Tendance H4 🟢 / D1 🟢 → ✅ aligné H4+D1" in msg
    msg2 = format_zone_message("touchee", {**z, "bias_d1": None, "aligned_h4d1": None})
    assert "D1 ?" in msg2
    rmsg = format_zone_message(
        "reaction", {**z, "trade_status": "closed", "trade_r": 2.0, "trade_exit": "tp"}
    )
    assert "Trade réel" in rmsg and "+2.00R" in rmsg


def test_notify_without_d1_data_still_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_DRY_RUN", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core import telegram as tg

    sent = []
    monkeypatch.setattr(tg, "send_telegram", lambda text, **kw: sent.append(text) or {"ok": True})
    z = {"id": "XAUUSD|H1|bull|t2", "symbol": "XAUUSD", "tf": "H1", "direction": "bull",
         "score": 4, "low": 90.0, "high": 110.0, "entry": 100.0, "sl": 90.0,
         "touched_at": "2026-10-06T08:00:00+00:00"}
    r = tg.notify_zone_event("touchee", z, force_dry=True)
    assert r and r.get("ok")
    assert len(sent) == 1 and "Tendance H4 ? / D1 ?" in sent[0]
    get_settings.cache_clear()


def test_digest_has_realistic_lines():
    from app.core.telegram import build_digest

    real = {"tp_r": 2.0, "n_closed": 10, "wr": 0.6, "avg_r": 0.42, "trades_per_day": 1.3,
            "n_unfilled": 4, "aligned": {"n": 5, "wr": 0.8, "avg_r": 1.0},
            "not_aligned": {"n": 5, "wr": 0.4, "avg_r": -0.1}}
    txt = build_digest([], label="test", stats={"realistic": real, "realistic_7d": real})
    assert "Stats réelles" in txt and "WR 60%" in txt and "aligné H4+D1 : 5" in txt


# --------------------------------------------------------------------- lifecycle + stats
def test_lifecycle_ignores_near_tp1_by_default(monkeypatch):
    from app.core.lifecycle import STATUS_REACTION, simulate_lifecycle

    monkeypatch.delenv("REACTION_COUNT_TP1", raising=False)
    rows = _flat(5, 120) + [(120, 121, 119, 120), (120, 121, 119, 120), (120, 121, 119, 120)]
    rows += [(115, 116, 99, 105), (105, 112, 104, 111)]  # touch + rally to 112 (1.2R, > tp1)
    df = _h1(rows)
    zone = {"ts_ob": df.index[3].isoformat(), "low": 90.0, "high": 110.0, "entry": 100.0,
            "sl": 90.0, "tp1": 111.0, "atr": 10.0, "direction": "bull", "tf": "H1"}
    life = simulate_lifecycle(df, zone, soft_reaction_r=0.0, reaction_r=2.0, require_entry_fill=False)
    assert life.status != STATUS_REACTION
    monkeypatch.setenv("REACTION_COUNT_TP1", "true")
    life2 = simulate_lifecycle(df, zone, soft_reaction_r=0.0, reaction_r=2.0, require_entry_fill=False)
    assert life2.status == STATUS_REACTION


def test_realistic_stats_split():
    from app.core.monitor import realistic_stats

    base = {"status": "reaction", "touched_at": "2026-09-01T10:00:00+00:00", "symbol": "EURUSD"}
    zones = [
        {**base, "trade_status": "closed", "trade_r": 2.0, "trade_exit": "tp", "aligned_h4d1": True},
        {**base, "trade_status": "closed", "trade_r": -1.0, "trade_exit": "sl", "aligned_h4d1": False},
        {**base, "trade_status": "closed", "trade_r": 0.3, "trade_exit": "time", "aligned_h4d1": None},
        {**base, "status": "touchee", "trade_status": "unfilled"},
        {**base, "status": "touchee", "trade_status": "pending"},
    ]
    s = realistic_stats(zones, gmap={"EURUSD": "FOREX"}, now="2026-09-15T10:00:00+00:00")
    assert s["n_closed"] == 3 and s["n_unfilled"] == 1 and s["n_pending"] == 1
    assert s["wr"] == pytest.approx(2 / 3)
    assert s["aligned"]["n"] == 1 and s["aligned"]["avg_r"] == 2.0
    assert s["not_aligned"]["n"] == 2
    assert s["trades_per_day"] == pytest.approx(3 / 10)
    assert s["by_group"]["FOREX"]["n"] == 3
