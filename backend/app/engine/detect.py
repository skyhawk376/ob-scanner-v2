"""OB detection + 5-star scoring (pure, no I/O)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import arrays_from_df, atr as calc_atr, find_pivots
from .params import EngineParams, params_for_tf
from .sessions import session_at
from .types import Zone

__all__ = [
    "detect_zones",
    "EngineParams",
    "params_for_tf",
    "is_fresh",
    "star1_fvg",
    "trend_from_pivots",
]


def trend_from_pivots(
    ph: list[tuple[int, float]],
    pl: list[tuple[int, float]],
    before: int,
) -> str:
    """HH+HL → bull; LH+LL → bear; else range."""
    highs = [(i, p) for i, p in ph if i < before]
    lows = [(i, p) for i, p in pl if i < before]
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    hh, lh = h2[1] > h1[1], h2[1] < h1[1]
    hl, ll = l2[1] > l1[1], l2[1] < l1[1]
    if hh and hl:
        return "bull"
    if lh and ll:
        return "bear"
    return "range"


def _eq_tol(price: float, atr_v: float, params: EngineParams) -> float:
    return max(params.liq_eq_atr * atr_v, params.liq_eq_pct * abs(price))


def _has_equal_levels(
    pivots: list[tuple[int, float]],
    *,
    band_lo: float,
    band_hi: float,
    before_idx: int,
    tol: float,
    series: np.ndarray,
    is_high: bool,
) -> bool:
    """≥2 untaken pivots in band within tol of each other."""
    in_band: list[float] = []
    for i, p in pivots:
        if i >= before_idx or not (band_lo <= p <= band_hi):
            continue
        if is_high:
            taken = bool(np.any(series[i + 1 : before_idx] > p + tol))
        else:
            taken = bool(np.any(series[i + 1 : before_idx] < p - tol))
        if not taken:
            in_band.append(p)
    if len(in_band) < 2:
        return False
    prices = sorted(in_band)
    for a in range(len(prices)):
        for b in range(a + 1, len(prices)):
            if abs(prices[b] - prices[a]) <= tol:
                return True
    return False


def _untaken_pivot_in_band(
    pivots: list[tuple[int, float]],
    *,
    band_lo: float,
    band_hi: float,
    before_idx: int,
    tol: float,
    high: np.ndarray,
    low: np.ndarray,
    is_high: bool,
) -> bool:
    for i, p in pivots:
        if i >= before_idx or not (band_lo <= p <= band_hi):
            continue
        if is_high:
            taken = bool(np.any(high[i + 1 : before_idx] >= p - tol))
        else:
            taken = bool(np.any(low[i + 1 : before_idx] <= p + tol))
        if not taken:
            return True
    return False


def is_fresh(
    low: np.ndarray,
    high: np.ndarray,
    ob_i: int,
    zone_lo: float,
    zone_hi: float,
    *,
    end: int | None = None,
) -> bool:
    """Virgin OB: after OB+2, no bar intersects the zone."""
    n = len(low)
    start = ob_i + 3
    if end is None:
        end = n
    if start >= end:
        return True
    for i in range(start, end):
        if low[i] <= zone_hi and high[i] >= zone_lo:
            return False
    return True


def star1_fvg(high: np.ndarray, low: np.ndarray, ob_i: int, bull: bool) -> bool:
    if ob_i + 2 >= len(high):
        return False
    if bull:
        return bool(high[ob_i] < low[ob_i + 2])
    return bool(low[ob_i] > high[ob_i + 2])


def _star5_h1(
    index: pd.DatetimeIndex,
    ob_i: int,
    leg_i: int,
    params: EngineParams,
) -> tuple[bool, str | None]:
    candidates = [ob_i]
    if ob_i + 1 < len(index):
        candidates.append(ob_i + 1)
    if leg_i not in candidates and 0 <= leg_i < len(index):
        candidates.append(leg_i)
    for i in candidates:
        label = session_at(
            index[i],
            london_start=params.london_start,
            london_end=params.london_end,
            ny_start=params.ny_start,
            ny_end=params.ny_end,
        )
        if label:
            return True, label
    return False, None


def _find_opposite_liquidity(
    direction: str,
    bos_i: int,
    end: int,
    ph: list[tuple[int, float]],
    pl: list[tuple[int, float]],
    high: np.ndarray,
    low: np.ndarray,
    entry: float,
    atr_v: float,
) -> float | None:
    tol = 0.05 * atr_v
    if direction == "bull":
        cands = []
        for i, p in ph:
            if i >= bos_i or p <= entry:
                continue
            taken = bool(np.any(high[i + 1 : end] >= p - tol))
            if not taken:
                cands.append(p)
        if cands:
            return float(min(cands))
        if bos_i < end:
            return float(np.max(high[bos_i:end]))
        return None
    cands = []
    for i, p in pl:
        if i >= bos_i or p >= entry:
            continue
        taken = bool(np.any(low[i + 1 : end] <= p + tol))
        if not taken:
            cands.append(p)
    if cands:
        return float(max(cands))
    if bos_i < end:
        return float(np.min(low[bos_i:end]))
    return None


def _displacement_ok(
    o: np.ndarray,
    c: np.ndarray,
    k: int,
    j: int,
    atr_v: float,
    params: EngineParams,
) -> bool:
    if not params.require_displacement:
        return True
    bodies = np.abs(c[k : j + 1] - o[k : j + 1])
    return bodies.size > 0 and float(np.max(bodies)) >= params.displacement_body_atr * atr_v


def _ts(ts) -> str:
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _build_zone(
    *,
    symbol: str,
    tf: str,
    direction: str,
    ob_i: int,
    bos_i: int,
    leg_i: int,
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    index: pd.DatetimeIndex,
    atr_v: float,
    ph: list[tuple[int, float]],
    pl: list[tuple[int, float]],
    params: EngineParams,
    n: int,
) -> Zone:
    bull = direction == "bull"
    zone_lo = float(l[ob_i])
    zone_hi = float(h[ob_i])
    zone_open = float(o[ob_i])
    zone_close = float(c[ob_i])

    s1 = star1_fvg(h, l, ob_i, bull)
    trend = trend_from_pivots(ph, pl, bos_i)
    s2 = (trend == "bull" and bull) or (trend == "bear" and not bull)

    if bull:
        swing_lo = float(np.min(l[leg_i : bos_i + 1]))
        swing_hi = float(np.max(h[bos_i:n]))
        if swing_hi < swing_lo:
            swing_hi = float(h[bos_i])
    else:
        swing_hi = float(np.max(h[leg_i : bos_i + 1]))
        swing_lo = float(np.min(l[bos_i:n]))
        if swing_lo > swing_hi:
            swing_lo = float(l[bos_i])

    fib_eq = swing_lo + 0.5 * (swing_hi - swing_lo)
    if bull:
        s3 = (
            zone_hi <= fib_eq
            if params.fib_strict
            else ((zone_lo + zone_hi) / 2 <= fib_eq)
        )
    else:
        s3 = (
            zone_lo >= fib_eq
            if params.fib_strict
            else ((zone_lo + zone_hi) / 2 >= fib_eq)
        )

    tol = _eq_tol((zone_lo + zone_hi) / 2, atr_v, params)
    if bull:
        band_lo = zone_lo - params.liq_band_atr * atr_v
        band_hi = zone_lo
        eq_liq = _has_equal_levels(
            pl,
            band_lo=band_lo,
            band_hi=band_hi,
            before_idx=ob_i,
            tol=tol,
            series=l,
            is_high=False,
        )
        untaken = _untaken_pivot_in_band(
            pl,
            band_lo=band_lo,
            band_hi=band_hi,
            before_idx=ob_i,
            tol=tol,
            high=h,
            low=l,
            is_high=False,
        )
    else:
        band_lo = zone_hi
        band_hi = zone_hi + params.liq_band_atr * atr_v
        eq_liq = _has_equal_levels(
            ph,
            band_lo=band_lo,
            band_hi=band_hi,
            before_idx=ob_i,
            tol=tol,
            series=h,
            is_high=True,
        )
        untaken = _untaken_pivot_in_band(
            ph,
            band_lo=band_lo,
            band_hi=band_hi,
            before_idx=ob_i,
            tol=tol,
            high=h,
            low=l,
            is_high=True,
        )
    s4 = (not eq_liq) and (not untaken)

    sweep = False
    if bull:
        for i, p in pl:
            if i >= ob_i:
                break
            if l[ob_i] < p - tol and c[ob_i] > p:
                sweep = True
                break
    else:
        for i, p in ph:
            if i >= ob_i:
                break
            if h[ob_i] > p + tol and c[ob_i] < p:
                sweep = True
                break

    star5_pending = tf.upper() in params.session_at_touch_tfs
    session_label = None
    if star5_pending:
        s5 = False
    else:
        s5, session_label = _star5_h1(index, ob_i, leg_i, params)

    fresh = is_fresh(l, h, ob_i, zone_lo, zone_hi, end=n)

    # Entry at OB edge (not mid): bull = OB low, bear = OB high.
    # SL beyond opposite (distal / invalidation) edge + ATR buffer.
    # "edge_proximal" = bull high / bear low (wider R).
    entry_mode = getattr(params, "entry_mode", "edge")
    if entry_mode == "mid":
        height = zone_hi - zone_lo
        if height > params.entry_mid_atr * atr_v:
            entry = (zone_lo + zone_hi) / 2.0
        else:
            entry = zone_open
    elif entry_mode == "edge_proximal":
        entry = zone_hi if bull else zone_lo
    else:
        # default "edge": bull = OB low, bear = OB high
        entry = zone_lo if bull else zone_hi

    if bull:
        sl = zone_lo - params.sl_buffer_atr * atr_v  # beyond opposite (distal) edge
        risk = entry - sl
        tp2 = entry + 2.0 * risk if risk > 0 else entry
        tp1 = _find_opposite_liquidity("bull", bos_i, n, ph, pl, h, l, entry, atr_v)
    else:
        sl = zone_hi + params.sl_buffer_atr * atr_v  # beyond opposite (distal) edge
        risk = sl - entry
        tp2 = entry - 2.0 * risk if risk > 0 else entry
        tp1 = _find_opposite_liquidity("bear", bos_i, n, ph, pl, h, l, entry, atr_v)

    rr_tp1 = None
    if tp1 is not None and risk > 0:
        rr_tp1 = ((tp1 - entry) if bull else (entry - tp1)) / risk
    rr_tp2 = 2.0 if risk > 0 else 0.0

    last_close = float(c[-1])
    mid = (zone_lo + zone_hi) / 2.0
    distance_atr = abs(mid - last_close) / atr_v if atr_v > 0 else 0.0
    score = int(s1) + int(s2) + int(s3) + int(s4) + int(s5)
    ts_ob = _ts(index[ob_i])

    return Zone(
        id=f"{symbol}|{tf.upper()}|{direction}|{ts_ob}",
        symbol=symbol,
        tf=tf.upper(),
        direction=direction,
        ob_index=ob_i,
        bos_index=bos_i,
        leg_index=leg_i,
        ts_ob=ts_ob,
        ts_bos=_ts(index[bos_i]),
        low=zone_lo,
        high=zone_hi,
        open=zone_open,
        close=zone_close,
        star1_fvg=s1,
        star2_trend=s2,
        star3_fib=s3,
        star4_liquidity=s4,
        star5_session=s5,
        star5_pending=star5_pending,
        score=score,
        fresh=fresh,
        trend=trend,
        entry=float(entry),
        sl=float(sl),
        tp1=float(tp1) if tp1 is not None else None,
        tp2=float(tp2),
        rr_tp1=float(rr_tp1) if rr_tp1 is not None else None,
        rr_tp2=float(rr_tp2),
        atr=float(atr_v),
        fib_eq=float(fib_eq),
        swing_low=float(swing_lo),
        swing_high=float(swing_hi),
        distance_atr=float(distance_atr),
        last_close=last_close,
        session_label=session_label,
        sweep=sweep,
        meta={"eq_liq_behind": eq_liq, "untaken_pivot_behind": untaken},
    )


def detect_zones(
    df: pd.DataFrame,
    *,
    symbol: str = "SYM",
    tf: str = "H1",
    params: EngineParams | None = None,
    min_score: int | None = None,
    require_fresh: bool | None = None,
    require_fvg: bool | None = None,
) -> list[Zone]:
    """Detect and score Order Blocks on OHLC DataFrame (DatetimeIndex)."""
    if df is None or len(df) < 30:
        return []

    params = params or params_for_tf(tf)
    if min_score is None:
        min_score = params.min_score
    if require_fresh is None:
        require_fresh = params.require_fresh
    if require_fvg is None:
        require_fvg = params.require_fvg

    work = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
    if params.lookback and len(work) > params.lookback:
        work = work.iloc[-params.lookback :]

    arr = arrays_from_df(work)
    o, h, l, c = arr["open"], arr["high"], arr["low"], arr["close"]
    n = len(work)
    index = work.index
    atr_arr = calc_atr(h, l, c, params.atr_len)
    ph, pl = find_pivots(h, l, params.pivot_n, confirmed_only=True, end=n)

    raw: list[Zone] = []
    last_bull_level: float | None = None
    last_bear_level: float | None = None

    for j in range(params.pivot_n * 2 + 2, n):
        atr_v = float(atr_arr[j])
        if atr_v <= 0 or np.isnan(atr_v):
            continue

        ph_before = [(i, p) for i, p in ph if i < j]
        if ph_before:
            pivot_i, pivot_p = ph_before[-1]
            if c[j] > pivot_p and pivot_p != last_bull_level:
                k = pivot_i + int(np.argmin(l[pivot_i : j + 1]))
                ob_i = None
                for i in range(k, -1, -1):
                    if c[i] < o[i]:
                        ob_i = i
                        break
                if (
                    ob_i is not None
                    and ob_i + 2 < n
                    and ob_i < j
                    and _displacement_ok(o, c, k, j, atr_v, params)
                ):
                    raw.append(
                        _build_zone(
                            symbol=symbol,
                            tf=tf,
                            direction="bull",
                            ob_i=ob_i,
                            bos_i=j,
                            leg_i=k,
                            o=o, h=h, l=l, c=c,
                            index=index,
                            atr_v=atr_v,
                            ph=ph, pl=pl,
                            params=params,
                            n=n,
                        )
                    )
                    last_bull_level = pivot_p

        pl_before = [(i, p) for i, p in pl if i < j]
        if pl_before:
            pivot_i, pivot_p = pl_before[-1]
            if c[j] < pivot_p and pivot_p != last_bear_level:
                k = pivot_i + int(np.argmax(h[pivot_i : j + 1]))
                ob_i = None
                for i in range(k, -1, -1):
                    if c[i] > o[i]:
                        ob_i = i
                        break
                if (
                    ob_i is not None
                    and ob_i + 2 < n
                    and ob_i < j
                    and _displacement_ok(o, c, k, j, atr_v, params)
                ):
                    raw.append(
                        _build_zone(
                            symbol=symbol,
                            tf=tf,
                            direction="bear",
                            ob_i=ob_i,
                            bos_i=j,
                            leg_i=k,
                            o=o, h=h, l=l, c=c,
                            index=index,
                            atr_v=atr_v,
                            ph=ph, pl=pl,
                            params=params,
                            n=n,
                        )
                    )
                    last_bear_level = pivot_p

    best: dict[tuple[str, int], Zone] = {}
    for z in raw:
        key = (z.direction, z.ob_index)
        prev = best.get(key)
        if prev is None or z.score > prev.score or (
            z.score == prev.score and z.bos_index > prev.bos_index
        ):
            best[key] = z

    out: list[Zone] = []
    for z in best.values():
        if require_fvg and not z.star1_fvg:
            continue
        if require_fresh and not z.fresh:
            continue
        if z.score < min_score:
            continue
        out.append(z)

    tf_rank = {"W": 0, "D": 1, "H4": 2, "H1": 3}
    out.sort(
        key=lambda z: (
            0 if z.symbol == "XAUUSD" else 1,
            -z.score,
            -int(z.star3_fib),
            tf_rank.get(z.tf.upper(), 9),
            z.distance_atr,
        )
    )
    return out
