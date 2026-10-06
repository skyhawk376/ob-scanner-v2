"""Faithful Python/numba port of OB Scanner **v1** (/workspace/ob-scanner/app.js, HEAD 58038f2) detection + 0-5 star
scoring + computeSlTp, plus a *causal* replay (when would the live panel first have shown the OB as 5 stars?).

v1 source of truth: v1_snapshot/app.js (copied read-only; v1 itself is never touched).

Full-hindsight port (`detect_full`) is checked bar-for-bar against the original JS in parity_test.py.
Causal replay (`detect_causal`): v1 scores every OB with whatever candles exist at scan time. FVG looks up to disp+3,
P/D up to disp+5 and "fresh" (= no close through the 50% mid) up to the last candle, so the star count of a given OB
changes as bars arrive. We re-score each OB on candles[:t+1] for t = disp .. disp+5 (flags are frozen after disp+5,
fresh can only be lost) and take the FIRST closed bar t where stars == 5 -> that is the alert bar.
"""
from __future__ import annotations
import numpy as np
from numba import njit

BODY_LOOKBACK = 20
BREAK_LOOKBACK = 10
BOS_LOOKBACK = 20
BODY_MULT = 1.5
OB_SEARCH = 8          # last opposing candle within 8 bars before displacement


@njit(cache=True)
def _fvg(h, l, i, bull, L):
    # checks m in [i, i-1, i+1] (classic 3-candle FVG with m as middle), m>=1 and m+1 < L
    for q in range(3):
        m = i if q == 0 else (i - 1 if q == 1 else i + 1)
        if m >= 1 and m + 1 < L:
            if bull and l[m + 1] > h[m - 1]:
                return True
            if (not bull) and h[m + 1] < l[m - 1]:
                return True
    a_end = min(L - 1, i + 3)
    for a in range(i + 1, a_end + 1):
        if bull and l[a] > h[i]:
            return True
        if (not bull) and h[a] < l[i]:
            return True
    return False


@njit(cache=True)
def _bos(h, l, c, i, bull):
    s = max(0, i - BOS_LOOKBACK)
    ph = -1e300; pl = 1e300
    for j in range(s, i):
        ph = max(ph, h[j]); pl = min(pl, l[j])
    return c[i] > ph if bull else c[i] < pl


@njit(cache=True)
def _sweep(h, l, i, bull):
    if i < 15:
        return False
    if bull:
        raid = 1e300; prior = 1e300
        for j in range(i - 5, i + 1): raid = min(raid, l[j])
        for j in range(i - 15, i - 5): prior = min(prior, l[j])
        return raid < prior
    raid = -1e300; prior = -1e300
    for j in range(i - 5, i + 1): raid = max(raid, h[j])
    for j in range(i - 15, i - 5): prior = max(prior, h[j])
    return raid > prior


@njit(cache=True)
def _pd(h, l, i, ob, mid, bull, L):
    s = max(0, i - 50)
    sl = 1e300
    for j in range(s, i): sl = min(sl, l[j])
    end = min(L - 1, i + 5)
    sh = -1e300
    for j in range(min(ob, i), end + 1): sh = max(sh, h[j])
    if not (sh > sl):
        return False
    half = sl + 0.5 * (sh - sl)
    return mid <= half if bull else mid >= half


@njit(cache=True)
def _candidates(o, h, l, c):
    """Displacement + OB candle, v1 dedupe (first displacement per (OB candle, side) wins).
    Returns arrays disp_i, ob_i, side(+1/-1)."""
    N = len(c)
    di = np.empty(N, np.int64); oi = np.empty(N, np.int64); sd = np.empty(N, np.int8)
    seen_b = np.zeros(N, np.bool_); seen_s = np.zeros(N, np.bool_)
    n = 0
    if N < BODY_LOOKBACK + BREAK_LOOKBACK + 3:
        return di[:0], oi[:0], sd[:0]
    for i in range(BODY_LOOKBACK, N):
        body = abs(c[i] - o[i])
        sm = 0.0
        for j in range(i - BODY_LOOKBACK, i): sm += abs(c[j] - o[j])
        avg = sm / BODY_LOOKBACK
        strong = avg > 0 and body >= BODY_MULT * avg
        ph = -1e300; pl = 1e300
        for j in range(max(0, i - BREAK_LOOKBACK), i):
            ph = max(ph, h[j]); pl = min(pl, l[j])
        bull = c[i] > o[i] and (strong or c[i] > ph)
        bear = c[i] < o[i] and (strong or c[i] < pl)
        if not bull and not bear:
            continue
        ob = -1
        for k in range(i - 1, max(0, i - OB_SEARCH) - 1, -1):
            if bull and c[k] < o[k]:
                ob = k; break
            if (not bull) and c[k] > o[k]:
                ob = k; break
        if ob < 0:
            continue
        if bull:
            if seen_b[ob]: continue
            seen_b[ob] = True
        else:
            if seen_s[ob]: continue
            seen_s[ob] = True
        di[n] = i; oi[n] = ob; sd[n] = 1 if bull else -1; n += 1
    return di[:n], oi[:n], sd[:n]


@njit(cache=True)
def _score(o, h, l, c, i, ob, bull, L):
    """flags (fvg, bos, sweep, fresh, pd) using only candles[:L]."""
    mid = (h[ob] + l[ob]) / 2.0
    fresh = True
    for m in range(i + 1, L):
        if bull and c[m] < mid: fresh = False; break
        if (not bull) and c[m] > mid: fresh = False; break
    f = np.zeros(5, np.bool_)
    f[0] = _fvg(h, l, i, bull, L); f[1] = _bos(h, l, c, i, bull); f[2] = _sweep(h, l, i, bull)
    f[3] = fresh; f[4] = _pd(h, l, i, ob, mid, bull, L)
    return f


@njit(cache=True)
def detect_full(o, h, l, c):
    """Exactly what app.js shows on a given candle array (hindsight within the array). flags matrix n x 5."""
    di, oi, sd = _candidates(o, h, l, c)
    n = len(di); N = len(c)
    F = np.zeros((n, 5), np.bool_)
    for q in range(n):
        F[q] = _score(o, h, l, c, di[q], oi[q], sd[q] > 0, N)
    return di, oi, sd, F


@njit(cache=True)
def detect_causal(o, h, l, c):
    """First bar t in [disp, disp+5] at which the OB scores 5 stars on candles[:t+1]; -1 if never."""
    di, oi, sd = _candidates(o, h, l, c)
    n = len(di); N = len(c)
    alert = np.full(n, -1, np.int64)
    for q in range(n):
        i = di[q]
        for t in range(i, min(i + 5, N - 1) + 1):
            f = _score(o, h, l, c, i, oi[q], sd[q] > 0, t + 1)
            if f.sum() == 5:
                alert[q] = t; break
            if not f[3]:
                break   # fresh lost -> can never become 5 stars again
    return di, oi, sd, alert


def sltp_v1(zhi, zlo, side):
    """app.js computeSlTp: entry = proximal edge (bull: high, bear: low); SL beyond the other edge + buffer;
    buffer = max(range*0.075, |entry|*1.5e-5); TP = entry +/- 2R."""
    zhi = np.asarray(zhi, float); zlo = np.asarray(zlo, float); side = np.asarray(side)
    entry = np.where(side > 0, zhi, zlo)
    buf = np.maximum((zhi - zlo).clip(min=0) * 0.075, np.abs(entry) * 1.5e-5)
    sl = np.where(side > 0, zlo - buf, zhi + buf)
    r = np.where(side > 0, entry - sl, sl - entry)
    tp = entry + side * 2 * r
    return entry, sl, tp
