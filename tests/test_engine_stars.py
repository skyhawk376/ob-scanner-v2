"""Unit tests for OB identification and each star on synthetic candles."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.detect import (
    detect_zones,
    is_fresh,
    star1_fvg,
    trend_from_pivots,
)
from app.engine.indicators import atr, find_pivots
from app.engine.params import EngineParams
from app.engine.sessions import session_at


def _df_from_rows(rows: list[dict], start="2026-03-10 08:00:00+00:00", freq="1h"):
    idx = pd.date_range(start=start, periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, index=idx)


def _ohlc(o, h, l, c, v=0.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# ★1 FVG
# ---------------------------------------------------------------------------
def test_star1_fvg_bullish():
    # OB at 0: high=10; bar+2 low=12 → gap
    h = np.array([10.0, 11.0, 13.0])
    l = np.array([8.0, 9.5, 12.0])
    assert star1_fvg(h, l, 0, True) is True
    assert star1_fvg(h, l, 0, False) is False


def test_star1_fvg_bearish():
    h = np.array([12.0, 11.0, 9.0])
    l = np.array([10.0, 9.5, 8.0])
    # bearish: low[OB]=10 > high[OB+2]=9
    assert star1_fvg(h, l, 0, False) is True
    assert star1_fvg(h, l, 0, True) is False


def test_star1_no_fvg():
    h = np.array([10.0, 11.0, 10.5])
    l = np.array([8.0, 9.0, 9.5])
    assert star1_fvg(h, l, 0, True) is False


# ---------------------------------------------------------------------------
# Fresh / virgin filter
# ---------------------------------------------------------------------------
def test_is_fresh_untouched():
    low = np.array([1, 1, 1, 5, 5, 5], dtype=float)
    high = np.array([2, 2, 2, 6, 6, 6], dtype=float)
    # zone [1,2], after OB+2 (start at 3) bars are 5-6 — no intersection
    assert is_fresh(low, high, ob_i=0, zone_lo=1.0, zone_hi=2.0) is True


def test_is_fresh_mitigated():
    low = np.array([1, 1, 1, 1.5, 5, 5], dtype=float)
    high = np.array([2, 2, 2, 3.0, 6, 6], dtype=float)
    assert is_fresh(low, high, ob_i=0, zone_lo=1.0, zone_hi=2.0) is False


# ---------------------------------------------------------------------------
# ★2 Trend HH/HL vs LH/LL
# ---------------------------------------------------------------------------
def test_trend_bull_hh_hl():
    ph = [(10, 100.0), (20, 110.0)]
    pl = [(5, 90.0), (15, 95.0)]
    assert trend_from_pivots(ph, pl, before=25) == "bull"


def test_trend_bear_lh_ll():
    ph = [(10, 110.0), (20, 100.0)]
    pl = [(5, 95.0), (15, 90.0)]
    assert trend_from_pivots(ph, pl, before=25) == "bear"


def test_trend_range():
    ph = [(10, 100.0), (20, 110.0)]
    pl = [(5, 95.0), (15, 90.0)]  # HH but LL → range
    assert trend_from_pivots(ph, pl, before=25) == "range"


# ---------------------------------------------------------------------------
# ★5 Session Europe/Paris
# ---------------------------------------------------------------------------
def test_session_london_paris():
    # 08:00 Paris = 06:00 UTC in summer (CEST UTC+2) on 2026-03-30
    ts = pd.Timestamp("2026-03-30 06:00:00", tz="UTC")
    assert session_at(ts) == "London"


def test_session_ny_paris():
    # 14:30 Paris = 12:30 UTC in CEST
    ts = pd.Timestamp("2026-03-30 12:30:00", tz="UTC")
    assert session_at(ts) == "NY"


def test_session_outside():
    ts = pd.Timestamp("2026-03-30 10:00:00", tz="UTC")  # 12:00 Paris
    assert session_at(ts) is None


# ---------------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------------
def test_find_pivots_strict():
    # clear peak at i=3, trough at i=7, N=2
    high = np.array([1, 2, 3, 10, 3, 2, 1, 2, 3, 2, 1], dtype=float)
    low = np.array([0, 1, 2, 3, 2, 1, 0.5, 0.1, 1, 2, 1], dtype=float)
    ph, pl = find_pivots(high, low, n=2, confirmed_only=True)
    assert any(i == 3 for i, _ in ph)
    assert any(i == 7 for i, _ in pl)


# ---------------------------------------------------------------------------
# Full OB detection on synthetic bullish impulse
# ---------------------------------------------------------------------------
def _synth_bullish_ob_series():
    """Build a series with HH/HL structure, bearish OB, FVG, London open, discount.

    Layout (N=2 for shorter series):
    - Build higher lows / higher highs
    - Bearish candle (OB) then strong push with FVG breaking prior swing high
    """
    rows = []
    # Warmup / ATR base around 100
    price = 100.0
    for i in range(40):
        o = price
        c = price + 0.2
        rows.append(_ohlc(o, max(o, c) + 0.3, min(o, c) - 0.3, c))
        price = c

    # Pivot low ~ index 40
    rows.append(_ohlc(price, price + 0.2, price - 1.5, price - 1.0))  # dip
    price = price - 1.0
    for _ in range(3):
        rows.append(_ohlc(price, price + 1.0, price - 0.2, price + 0.8))
        price += 0.8
    # Pivot high
    rows.append(_ohlc(price, price + 2.0, price - 0.2, price + 1.5))
    swing_high = price + 2.0
    price = price + 1.5
    for _ in range(3):
        rows.append(_ohlc(price, price + 0.3, price - 0.8, price - 0.5))
        price -= 0.5

    # Higher low
    rows.append(_ohlc(price, price + 0.3, price - 1.0, price - 0.3))
    price = price - 0.3
    for _ in range(3):
        rows.append(_ohlc(price, price + 1.2, price - 0.2, price + 1.0))
        price += 1.0

    # Second pivot high (HH)
    rows.append(_ohlc(price, price + 2.5, price - 0.2, price + 2.0))
    pivot_high = price + 2.5
    price = price + 2.0
    for _ in range(3):
        rows.append(_ohlc(price, price + 0.2, price - 0.6, price - 0.4))
        price -= 0.4

    # Pullback low (leg), then bearish OB candle deep in discount, then impulse with FVG
    # Bearish OB
    ob_open = price
    ob_close = price - 1.2
    ob_low = ob_close - 0.3
    ob_high = ob_open + 0.1
    rows.append(_ohlc(ob_open, ob_high, ob_low, ob_close))  # OB
    # Impulse bar 1
    rows.append(_ohlc(ob_close, ob_close + 2.0, ob_close - 0.1, ob_close + 1.8))
    # Impulse bar 2 — FVG: low > OB high
    fvg_low = ob_high + 0.5
    rows.append(_ohlc(fvg_low + 0.2, fvg_low + 3.0, fvg_low, fvg_low + 2.5))
    price = fvg_low + 2.5
    # Continue up through prior pivot high (BOS)
    while price <= pivot_high + 1.0:
        rows.append(_ohlc(price, price + 1.5, price - 0.1, price + 1.2))
        price += 1.2
    # Extra bars so OB stays fresh (price stays above zone)
    for _ in range(15):
        rows.append(_ohlc(price, price + 0.5, price - 0.2, price + 0.3))
        price += 0.3

    # Start at London session: 2026-03-30 06:00 UTC = 08:00 Paris
    return _df_from_rows(rows, start="2026-03-30 06:00:00+00:00", freq="1h")


def test_detect_bullish_ob_with_fvg():
    df = _synth_bullish_ob_series()
    params = EngineParams(
        pivot_n=2,
        lookback=500,
        min_score=1,
        require_fresh=True,
        require_fvg=True,
        fib_strict=True,
        # relax liq for synthetic
        liq_band_atr=0.1,
    )
    zones = detect_zones(df, symbol="TEST", tf="H1", params=params, min_score=1)
    assert len(zones) >= 1
    bulls = [z for z in zones if z.direction == "bull"]
    assert bulls, "expected at least one bullish OB"
    z = bulls[0]
    assert z.star1_fvg is True
    assert z.fresh is True
    assert z.low <= z.high
    assert z.entry == z.low  # bull entry = OB low
    assert z.sl < z.low  # SL beyond opposite (distal) edge
    assert z.tp2 > z.entry
    assert z.score >= 1


def test_detect_filters_min_score():
    df = _synth_bullish_ob_series()
    params = EngineParams(pivot_n=2, lookback=500, liq_band_atr=0.1)
    z_all = detect_zones(df, symbol="TEST", tf="H1", params=params, min_score=1, require_fresh=True)
    z_hi = detect_zones(df, symbol="TEST", tf="H1", params=params, min_score=5, require_fresh=True)
    assert len(z_hi) <= len(z_all)


def test_atr_positive():
    h = np.linspace(10, 20, 50) + np.random.default_rng(0).normal(0, 0.1, 50)
    l = h - 1.0
    c = (h + l) / 2
    a = atr(h, l, c, 14)
    assert np.all(a[13:] > 0)


def test_h4_star5_pending():
    df = _synth_bullish_ob_series()
    # reuse as fake H4 bars
    params = EngineParams(pivot_n=2, lookback=500, min_score=1, liq_band_atr=0.1)
    zones = detect_zones(df, symbol="TEST", tf="H4", params=params, min_score=1)
    if zones:
        assert zones[0].star5_pending is True
        assert zones[0].star5_session is False
