"""v3 engine: detection, stars, patterns, trigger, trade management (BE / TP / SL)."""
from __future__ import annotations

import pandas as pd
import pytest

from app.v3 import params as P
from app.v3.detect import detect_zones, in_session
from app.v3.patterns import reversal_kind
from app.v3.sim import simulate_zone
from v3_fixtures import FLAT_AT, HAMMER, TOUCH, bull_h1, flat, frame, m15_for


def _zone(h1):
    zs = [z for z in detect_zones(h1, "H1", "TEST", "METAUX") if z["direction"] == "bull"]
    assert len(zs) == 1
    return zs[0]


# ---------------------------------------------------------------- detection
def test_bull_ob_full_range_with_wicks_and_fvg():
    z = _zone(bull_h1())
    assert (z["low"], z["high"]) == (99.6, 100.4)
    assert z["fvg_low"] == 100.4 and z["fvg_high"] == 101.0
    assert z["armed_ts"] == bull_h1().index[23].isoformat()


def test_no_fvg_no_zone():
    rows = flat(20) + [(100.2, 100.4, 99.6, 99.8), (99.9, 101.5, 99.8, 101.4),
                       (101.4, 102.5, 100.3, 102.3), (102.3, 102.4, 101.4, 102.0), (102.0, 102.1, 101.3, 101.9)]
    assert not [z for z in detect_zones(frame(rows), "H1", "T") if z["direction"] == "bull"]


def test_weak_impulse_no_zone():
    rows = flat(20) + [(100.2, 100.4, 99.6, 99.8), (99.9, 100.6, 99.8, 100.5),
                       (100.5, 100.9, 100.45, 100.8), (100.8, 101.0, 100.6, 100.9), (100.9, 101.0, 100.7, 100.8)]
    assert not [z for z in detect_zones(frame(rows), "H1", "T") if z["direction"] == "bull"]


def test_forming_fvg_candle_not_detected_live():
    h1 = bull_h1(touch_bar=False).iloc[:23]          # bar 22 (FVG 3rd candle) is the last bar
    now = h1.index[22] + pd.Timedelta(minutes=30)     # still forming
    assert not [z for z in detect_zones(h1, "H1", "T", now=now) if z["direction"] == "bull"]
    assert [z for z in detect_zones(h1, "H1", "T", now=now + pd.Timedelta(minutes=30)) if z["direction"] == "bull"]


def test_bear_mirror():
    inv = bull_h1()
    m = 200.0
    bear = pd.DataFrame({"open": m - inv.open, "high": m - inv.low, "low": m - inv.high, "close": m - inv.close}, index=inv.index)
    zs = [z for z in detect_zones(bear, "H1", "T") if z["direction"] == "bear"]
    assert len(zs) == 1 and (zs[0]["low"], zs[0]["high"]) == (99.6, 100.4)


# ---------------------------------------------------------------- stars
def test_session_star_dst_aware():
    assert in_session(pd.Timestamp("2026-03-27 07:30", tz="UTC"), "H1")      # 08:30 CET
    assert not in_session(pd.Timestamp("2026-03-27 06:30", tz="UTC"), "H1")  # 07:30 CET
    assert in_session(pd.Timestamp("2026-03-30 06:30", tz="UTC"), "H1")      # 08:30 CEST
    assert not in_session(pd.Timestamp("2026-03-30 19:00", tz="UTC"), "H1")  # 21:00 CEST
    assert not in_session(pd.Timestamp("2026-03-28 10:00", tz="UTC"), "H1")  # Saturday
    assert not in_session(pd.Timestamp("2026-03-30 10:00", tz="UTC"), "D")   # D/W: never


def test_trend_star_dow_and_range():
    # zig-zag with higher highs and higher lows before the OB
    rows = []
    p = 100.0
    for k in range(6):
        for _ in range(4):
            p += 0.5
            rows.append((p - 0.5, p + 0.1, p - 0.55, p))
        for _ in range(3):
            p -= 0.4
            rows.append((p + 0.4, p + 0.45, p - 0.1, p))
    base = p
    rows += [(base + 0.2, base + 0.4, base - 0.4, base - 0.2), (base - 0.1, base + 2.0, base - 0.2, base + 1.9),
             (base + 1.9, base + 3.0, base + 1.0, base + 2.8), (base + 2.8, base + 3.2, base + 2.5, base + 3.0)]
    zs = [z for z in detect_zones(frame(rows), "H1", "T") if z["direction"] == "bull" and z["ts_ob"] == frame(rows).index[-4].isoformat()]
    assert zs and zs[0]["star_trend"] and zs[0]["trend"] == "haussière"
    assert not _zone(bull_h1())["star_trend"]       # flat market = range -> no star


def test_liquidity_sweep_star():
    rows = flat(12)
    rows += [(100.0, 100.3, 98.0, 99.9)]             # 12: swing low 98.0 (pivot)
    rows += [(100.0, 100.5, 99.5, 100.0)] * 8        # untaken
    rows += [(100.0, 100.2, 97.8, 99.0)]             # 21 OB sweeps 98.0 (bearish)
    rows += [(99.1, 101.5, 99.0, 101.4), (101.4, 102.5, 100.6, 102.3), (102.3, 103, 102, 102.8)]
    zs = [z for z in detect_zones(frame(rows), "H1", "T") if z["direction"] == "bull"]
    assert zs and zs[-1]["star_liquidity"]
    assert not _zone(bull_h1())["star_liquidity"]


def test_session_star_on_ob_bar():
    z = _zone(bull_h1())  # OB bar 20 = 2026-10-06 02:00 UTC = 04:00 Paris -> out of session
    assert z["star_session"] is False


# ---------------------------------------------------------------- patterns
@pytest.mark.parametrize(
    "bull,prev,cur,kind",
    [
        (True, (101, 101.2, 100.2, 100.4), (100.3, 101.3, 100.2, 101.2), "englobante"),
        (True, (100.6, 100.7, 100.3, 100.4), HAMMER, "marteau"),
        (True, (100.6, 100.7, 100.3, 100.4), (100.5, 100.9, 100.1, 100.2), None),
        (False, (100.4, 101.2, 100.2, 101.0), (101.1, 101.2, 100.1, 100.3), "englobante"),
        (False, (100.4, 100.6, 100.3, 100.5), (100.5, 101.2, 100.4, 100.45), "étoile filante"),
    ],
)
def test_reversal_patterns(bull, prev, cur, kind):
    assert reversal_kind(bull, prev[0], prev[3], *cur) == kind


# ---------------------------------------------------------------- trigger + trade
def _z4(h1):
    """Fixture zone forced to 4★ at first touch (Tendance + Liquidité + Vierge + Fibo)."""
    return {**_zone(h1), "star_trend": True, "star_liquidity": True}


def _run(trigger_rows, h1=None, now=None):
    h1 = h1 if h1 is not None else bull_h1()
    m15 = m15_for(h1, trigger_rows)
    return simulate_zone(_z4(h1), h1, m15, now)


def test_entry_on_hammer_close_and_be_exit():
    rows = [TOUCH, HAMMER, FLAT_AT(101.0), (101.0, 101.7, 100.9, 101.6),   # +1R reached (BE)
            (101.6, 101.6, 100.4, 100.5)] + [FLAT_AT(100.5)] * 10           # back to entry -> BE
    r = _run(rows)
    tr = r["trade"]
    assert tr["trigger"] == "marteau" and tr["ltf"] == "M15"
    assert tr["entry"] == 100.55
    assert tr["sl"] == pytest.approx(99.6 - P.SL_BUFFER_ATR * _zone(bull_h1())["atr"])
    assert tr["tp"] == pytest.approx(100.55 + 2 * (100.55 - tr["sl"]))
    assert tr["be_ts"] is not None and tr["exit"] == "be_exit" and tr["r_gross"] == 0.0
    assert tr["r_net"] < 0  # costs
    assert [e["kind"] for e in r["events"]] == ["touch", "entry", "be", "exit"]
    assert r["state"] == "be_exit"


def test_tp_after_be():
    rows = [TOUCH, HAMMER, (100.6, 101.7, 100.6, 101.6), (101.6, 102.9, 101.5, 102.8)] + [FLAT_AT(102.8)] * 10
    tr = _run(rows)["trade"]
    assert tr["exit"] == "tp" and tr["r_gross"] == 2.0 and tr["be_ts"]


def test_sl_before_be():
    rows = [TOUCH, HAMMER, (100.5, 100.6, 99.4, 99.5)] + [FLAT_AT(99.5)] * 10
    tr = _run(rows)["trade"]
    assert tr["exit"] == "sl" and tr["r_gross"] == -1.0 and tr["be_ts"] is None


def test_no_time_stop_trade_stays_open():
    rows = [TOUCH, HAMMER] + [FLAT_AT(100.8)] * 14
    r = _run(rows)
    assert r["trade"]["status"] == "open" and r["state"] == "entered"
    assert [e["kind"] for e in r["events"]] == ["touch", "entry"]


def test_no_trigger_in_window_then_waiting_and_virgin_lost():
    rows = [TOUCH] + [FLAT_AT(100.35)] * 11            # stays in zone, no pattern for 3 bars
    r = _run(rows)
    assert r["trade"] is None and r["state"] in ("waiting",)
    assert r["touches"][0]["stars"]["vierge"] is True


def test_invalidation_close_beyond_distal_blocks_entry():
    h1 = bull_h1(invalidate=True)
    rows = [TOUCH, (100.3, 100.35, 99.2, 99.3), (99.3, 99.4, 99.0, 99.3), (99.3, 99.5, 99.2, 99.4)]
    rows += [(99.4, 99.45, 98.9, 99.0), (99.0, 99.6, 98.95, 99.55)] + [FLAT_AT(99.5)] * 6
    r = _run(rows, h1=h1)
    assert r["state"] == "invalidated" and r["trade"] is None


def test_live_window_open_state_touched_and_closed_candles_only():
    h1 = bull_h1()
    m15 = m15_for(h1, [TOUCH, HAMMER])
    z = _z4(h1)
    now = h1.index[28] + pd.Timedelta(minutes=29)       # hammer (15–30) not closed yet
    r = simulate_zone(z, h1.iloc[:29], m15, now)
    assert r["state"] == "touched" and r["trade"] is None
    r2 = simulate_zone(z, h1.iloc[:29], m15, now + pd.Timedelta(minutes=1))
    assert r2["trade"] and r2["trade"]["entry_ts"] == (h1.index[28] + pd.Timedelta(minutes=30)).isoformat()


def test_score_stars_and_fib():
    r = _run([TOUCH, HAMMER] + [FLAT_AT(100.8)] * 10)
    st = r["touches"][0]["stars"]
    assert st["fibo"] is True and st["vierge"] is True
    assert r["touches"][0]["score"] == sum(st.values())


def test_costs_and_tf_mapping():
    from app.core.timeframes import normalize_tf
    from app.v3.costs import cost_r

    assert normalize_tf("1m") == "M1" and P.LOWER_TF["M5"] == "M1" and P.LOWER_TF["W"] == "D"
    assert cost_r("XAUUSD", 2400.0, 2.0, "METAUX") == pytest.approx((0.25 + 0.07 + 0.10 * 2) / 2.0)
    assert cost_r("EURUSD", 1.1, 0.0010, "FOREX", stop_exit=False) == pytest.approx((0.2 + 0.6 + 0.2) * 1e-4 / 0.0010)
    assert cost_r("NAS100", 20000, 20, "NQ100") > 0 and cost_r("DOGE", 0.1, 0.002, "CRYPTO") > 0


def test_second_unit_index_and_ns_now():
    """Prod cache files carry datetime64[s]/[ms] indexes; `now` has sub-second precision."""
    h1 = bull_h1()
    h1s = h1.copy()
    h1s.index = h1s.index.as_unit("s")
    m15 = m15_for(h1, [TOUCH, HAMMER] + [FLAT_AT(100.8)] * 10)
    m15.index = m15.index.as_unit("ms")
    now = h1.index[-1] + pd.Timedelta(hours=1, microseconds=123457, nanoseconds=11)
    zs = detect_zones(h1s, "H1", "T", now=now)
    assert zs
    r = simulate_zone({**[z for z in zs if z["direction"] == "bull"][0], "star_trend": True, "star_liquidity": True}, h1s, m15, now)
    assert r["trade"] is not None
