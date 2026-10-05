import pandas as pd
from app.core.lifecycle import (
    STATUS_ECHEC,
    STATUS_REACTION,
    STATUS_TOUCHEE,
    simulate_lifecycle,
)


def _df(rows, start="2026-03-30 06:00:00+00:00"):
    idx = pd.date_range(start=start, periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_touch_then_reaction_bull():
    # flat then zone touch then rally +1R
    rows = []
    for i in range(10):
        rows.append({"open": 100, "high": 100.5, "low": 99.5, "close": 100, "volume": 0})
    # OB candle at i=10 — we set ts_ob to that bar
    rows.append({"open": 100, "high": 100.2, "low": 98.0, "close": 98.5, "volume": 0})  # 10
    rows.append({"open": 98.5, "high": 101, "low": 98.4, "close": 100.5, "volume": 0})  # 11
    rows.append({"open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 0})  # 12 OB+2
    # away
    for _ in range(3):
        rows.append({"open": 102, "high": 103, "low": 101.5, "close": 102.5, "volume": 0})
    # touch zone [98, 100.2]
    rows.append({"open": 101, "high": 101.2, "low": 99.0, "close": 99.5, "volume": 0})
    # reaction +1R: entry=100, sl=97.9 → R≈2.1 → need high >= 102.1
    rows.append({"open": 99.5, "high": 103.0, "low": 99.4, "close": 102.5, "volume": 0})
    df = _df(rows)
    zone = {
        "ts_ob": df.index[10].isoformat(),
        "low": 98.0,
        "high": 100.2,
        "entry": 100.0,
        "sl": 97.9,
        "tp1": 105.0,
        "atr": 1.0,
        "direction": "bull",
        "tf": "H1",
        "star1_fvg": True,
        "star2_trend": True,
        "star3_fib": True,
        "star4_liquidity": True,
        "star5_session": False,
        "star5_pending": False,
        "score": 4,
    }
    life = simulate_lifecycle(df, zone)
    assert life.status == STATUS_REACTION
    assert life.touched_at is not None
    assert life.mfe_r >= 1.0


def test_touch_then_sl_bear():
    rows = []
    for i in range(10):
        rows.append({"open": 50, "high": 50.5, "low": 49.5, "close": 50, "volume": 0})
    rows.append({"open": 50, "high": 52, "low": 49.8, "close": 51.5, "volume": 0})  # OB bullish candle for bear OB
    rows.append({"open": 51.5, "high": 51.6, "low": 48, "close": 48.5, "volume": 0})
    rows.append({"open": 48.5, "high": 49, "low": 47, "close": 47.5, "volume": 0})
    for _ in range(3):
        rows.append({"open": 47, "high": 47.5, "low": 46, "close": 46.5, "volume": 0})
    # touch zone [49.8, 52]
    rows.append({"open": 48, "high": 50.5, "low": 47.8, "close": 50.0, "volume": 0})
    # SL hit (sl above zone)
    rows.append({"open": 50, "high": 53.0, "low": 49.9, "close": 52.5, "volume": 0})
    df = _df(rows)
    zone = {
        "ts_ob": df.index[10].isoformat(),
        "low": 49.8,
        "high": 52.0,
        "entry": 51.0,
        "sl": 52.2,
        "tp1": 45.0,
        "atr": 1.0,
        "direction": "bear",
        "tf": "H1",
        "score": 4,
    }
    life = simulate_lifecycle(df, zone)
    assert life.status == STATUS_ECHEC
