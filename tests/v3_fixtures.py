"""Synthetic candles for the v3 tests: a clean bull OB on H1 + its M15 lower TF."""
from __future__ import annotations

import pandas as pd

T0 = pd.Timestamp("2026-10-05 06:00", tz="UTC")  # Monday 08:00 Paris (CEST) at bar 0


def frame(rows, start=T0, minutes=60):
    idx = pd.date_range(start, periods=len(rows), freq=f"{minutes}min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).astype(float)


def flat(n, p=100.0):
    # alternating tiny candles (range 1.0) -> ATR ~ 1, no OB (bodies 0)
    return [(p, p + 0.5, p - 0.5, p) for _ in range(n)]


def bull_h1(touch_bar=True, invalidate=False):
    rows = flat(20)
    rows += [
        (100.2, 100.4, 99.6, 99.8),     # 20 OB (bearish) zone 99.6-100.4
        (99.9, 101.5, 99.8, 101.4),     # 21 impulse
        (101.4, 102.5, 101.0, 102.3),   # 22 -> FVG: low 101.0 > high[20] 100.4
        (102.3, 103.0, 102.0, 102.8),   # 23 armed
        (102.8, 103.0, 102.2, 102.5),
        (102.5, 102.7, 101.9, 102.0),
        (102.0, 102.2, 101.5, 101.7),
        (101.7, 101.9, 101.2, 101.5),   # 27
    ]
    if touch_bar:
        rows.append((101.5, 101.6, 100.3, 100.6 if not invalidate else 99.4))  # 28 touch
        rows += [(100.6, 101.7, 100.4, 101.6), (101.6, 101.8, 100.4, 100.5), (100.5, 100.8, 100.3, 100.6)]
        rows += [(100.6, 101.0, 100.5, 100.8)] * 4
    return frame(rows)


def m15_for(h1: pd.DataFrame, trigger_rows=None, start_bar=28):
    """M15 bars: 4 per H1 bar, flat inside each H1 bar except from `start_bar` where
    `trigger_rows` (list of OHLC) are inserted."""
    rows, times = [], []
    for i, (ts, r) in enumerate(h1.iterrows()):
        if i < start_bar or not trigger_rows:
            for q in range(4):
                p = r["close"]
                rows.append((p, p + 0.05, p - 0.05, p))
                times.append(ts + pd.Timedelta(minutes=15 * q))
    if trigger_rows:
        t = h1.index[start_bar]
        for q, row in enumerate(trigger_rows):
            rows.append(row)
            times.append(t + pd.Timedelta(minutes=15 * q))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(times)).astype(float)


TOUCH = (101.5, 101.5, 100.3, 100.4)        # bearish M15 entering the zone (no pattern)
HAMMER = (100.5, 100.6, 99.9, 100.55)       # long lower wick, close in upper third
FLAT_AT = lambda p: (p, p + 0.02, p - 0.02, p)  # noqa: E731
