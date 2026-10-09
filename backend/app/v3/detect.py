"""v3 OB detection + static stars (Tendance, Liquidité prise, Session).

Dynamic stars (OB jamais touché, Fibo 0.5) depend on the evaluation time and are
computed in sim.py. Everything here is causal: an OB at bar i only uses bars <= i
for the stars and bars <= i+IMPULSE_BARS for the impulse/FVG.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import params as P

PARIS = ZoneInfo("Europe/Paris")


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = P.ATR_LEN) -> np.ndarray:
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    if len(tr) < n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def pivots(high: np.ndarray, low: np.ndarray, n: int = P.PIVOT_N) -> tuple[np.ndarray, np.ndarray]:
    """Boolean arrays: strict fractal pivot high/low at index p (confirmed at p+n)."""
    L = len(high)
    ph = np.zeros(L, bool)
    pl = np.zeros(L, bool)
    if L < 2 * n + 1:
        return ph, pl
    from numpy.lib.stride_tricks import sliding_window_view as sw

    wh = sw(high, 2 * n + 1)
    wl = sw(low, 2 * n + 1)
    c = n
    hmax = wh.max(axis=1)
    lmin = wl.min(axis=1)
    ph[n : L - n] = (wh[:, c] == hmax) & ((wh == hmax[:, None]).sum(axis=1) == 1)
    pl[n : L - n] = (wl[:, c] == lmin) & ((wl == lmin[:, None]).sum(axis=1) == 1)
    return ph, pl


def in_session(ts: pd.Timestamp, tf: str) -> bool:
    """★ Session: candle OPEN time Mon–Fri within [08:00, 21:00) Paris (zoneinfo → DST-aware)."""
    if tf not in P.SESSION_TFS:
        return False
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    loc: datetime = t.tz_convert(PARIS).to_pydatetime()
    if loc.weekday() >= 5:
        return False
    hm = (loc.hour, loc.minute)
    return P.SESSION_START <= hm < P.SESSION_END


def dow_trend(ph_idx: np.ndarray, pl_idx: np.ndarray, high, low, i: int) -> int:
    """+1 bull (HH+HL), -1 bear (LH+LL), 0 range, using pivots confirmed at bar i."""
    hs = ph_idx[ph_idx + P.PIVOT_N <= i]
    ls = pl_idx[pl_idx + P.PIVOT_N <= i]
    if len(hs) < 2 or len(ls) < 2:
        return 0
    h1, h2 = high[hs[-2]], high[hs[-1]]
    l1, l2 = low[ls[-2]], low[ls[-1]]
    if h2 > h1 and l2 > l1:
        return 1
    if h2 < h1 and l2 < l1:
        return -1
    return 0


def liquidity_swept(bull: bool, piv_idx: np.ndarray, high, low, i: int) -> bool:
    """★ Liquidité prise: an untaken prior swing low (bull) / high (bear) is pierced by
    bars [i-SWEEP_WIN+1 .. i] (sweep happens before / on the OB candle)."""
    s0 = i - P.SWEEP_WIN + 1
    if s0 <= 0:
        return False
    cand = piv_idx[(piv_idx >= i - P.LIQ_LOOKBACK) & (piv_idx < s0) & (piv_idx + P.PIVOT_N <= i)]
    if len(cand) == 0:
        return False
    if bull:
        sweep_low = low[s0 : i + 1].min()
        for p in cand:
            lvl = low[p]
            between = low[p + 1 : s0]
            if (len(between) == 0 or between.min() >= lvl) and sweep_low < lvl:
                return True
    else:
        sweep_high = high[s0 : i + 1].max()
        for p in cand:
            lvl = high[p]
            between = high[p + 1 : s0]
            if (len(between) == 0 or between.max() <= lvl) and sweep_high > lvl:
                return True
    return False


def _iso(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert("UTC").isoformat()


def detect_zones(
    df: pd.DataFrame, tf: str, symbol: str, group: str = "", now: pd.Timestamp | None = None
) -> list[dict[str, Any]]:
    """All v3 OB zones in `df`. The FVG's third candle must be CLOSED at `now`
    (default: all bars treated as closed, i.e. backtest), so a stored zone never changes."""
    if df is None or len(df) < P.ATR_LEN + 3:
        return []
    from .sim import norm_index

    df = norm_index(df)
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index
    a = atr(h, l, c)
    phb, plb = pivots(h, l)
    ph_idx = np.flatnonzero(phb)
    pl_idx = np.flatnonzero(plb)
    n = len(df)
    if now is not None:
        now_ts = pd.Timestamp(now)
        if now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize("UTC")
        step = pd.Timedelta(minutes=P.TF_MIN.get(tf, 60))
        n_closed = int(np.searchsorted(idx, now_ts - step, side="right"))
    else:
        n_closed = n
    out: list[dict[str, Any]] = []
    for i in range(P.ATR_LEN, n - 2):
        av = a[i]
        if not np.isfinite(av) or av <= 0:
            continue
        for bull in (True, False):
            # OB colour opposite to the move, next candle in the move direction
            if bull and not (c[i] < o[i] and c[i + 1] > o[i + 1]):
                continue
            if not bull and not (c[i] > o[i] and c[i + 1] < o[i + 1]):
                continue
            last = min(i + P.IMPULSE_BARS, n - 1)
            if bull:
                ext = h[i + 1 : last + 1].max()
                if ext - h[i] < P.IMPULSE_ATR * av:
                    continue
            else:
                ext = l[i + 1 : last + 1].min()
                if l[i] - ext < P.IMPULSE_ATR * av:
                    continue
            # FVG mandatory inside the impulse
            fvg = None
            for k in range(i + 1, last):
                if bull and l[k + 1] > h[k - 1]:
                    fvg = (k, float(h[k - 1]), float(l[k + 1]))
                    break
                if not bull and h[k + 1] < l[k - 1]:
                    fvg = (k, float(h[k + 1]), float(l[k - 1]))
                    break
            if fvg is None or fvg[0] + 1 >= n_closed:
                continue
            armed = fvg[0] + 2
            if armed >= n + 1:
                continue
            tr = dow_trend(ph_idx, pl_idx, h, l, i)
            star_trend = tr == (1 if bull else -1)
            star_liq = liquidity_swept(bull, pl_idx if bull else ph_idx, h, l, i)
            star_sess = in_session(idx[i], tf)
            d = "bull" if bull else "bear"
            ts_ob = _iso(idx[i])
            out.append(
                {
                    "id": f"v3|{symbol}|{tf}|{d}|{ts_ob}",
                    "symbol": symbol,
                    "group": group,
                    "tf": tf,
                    "direction": d,
                    "ts_ob": ts_ob,
                    "low": float(l[i]),
                    "high": float(h[i]),
                    "atr": float(av),
                    "fvg_low": fvg[1],
                    "fvg_high": fvg[2],
                    "armed_ts": _iso(idx[armed]) if armed < n else None,
                    "trend": {1: "haussière", -1: "baissière", 0: "range"}[tr],
                    "star_trend": bool(star_trend),
                    "star_liquidity": bool(star_liq),
                    "star_session": bool(star_sess),
                }
            )
    return out
