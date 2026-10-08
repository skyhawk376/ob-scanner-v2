"""Shape features of a scanner Order Block + outcome helpers (pure numpy, no I/O).

All distances are in ATR units (ATR = the zone's ATR at the BOS bar, as the scanner).
Indices refer to the bar arrays passed in (o, h, l, c of the zone's TF).

Zone geometry used (identical to backend/app/engine/detect.py):
  bull: BOS bar j closes above the last pivot high (piv_i, piv_p); leg extreme k = argmin(low[piv_i..j]);
        OB = last bearish candle at/before k; zone = OB full range [low, high];
        entry = mid if height > 1 ATR else OB open; SL = low - 0.05 ATR; TP = +2R.
  bear: mirror.
"""
from __future__ import annotations

import math

import numpy as np

# Pre-registered "textbook OB" criteria (fixed BEFORE looking at outcomes — see PREREG.md)
TEXTBOOK = {
    "T1_displacement": "max body of OB+1..OB+2 >= 1.0 ATR",
    "T2_fvg": "FVG (OB vs OB+2) >= 0.25 ATR",
    "T3_bos_fast": "BOS within 10 bars of the OB",
    "T4_bos_margin": "BOS close beyond the broken pivot by >= 0.10 ATR",
    "T5_origin": "OB is the origin of the move: leg extreme not more than 0.10 ATR beyond the zone's distal edge",
    "T6_not_chop": "<= 5 of the 10 bars before the OB overlap the zone",
    "T7_body": "OB candle body >= 25% of its range (not a wick-only zone)",
    "T8_size": "0.2 <= zone height <= 2.5 ATR",
}


def strict_pivots(h: np.ndarray, l: np.ndarray, N: int, end: int | None = None):
    """Strict fractal pivots (same as Pine/scanner: h[i] > h[i±k] for k=1..N), confirmed by end-1."""
    n = len(h) if end is None else end
    ph, pl = [], []
    for i in range(N, n - N):
        hi = h[i]
        lo = l[i]
        if all(hi > h[i - k] and hi > h[i + k] for k in range(1, N + 1)):
            ph.append((i, float(hi)))
        if all(lo < l[i - k] and lo < l[i + k] for k in range(1, N + 1)):
            pl.append((i, float(lo)))
    return ph, pl


def session_label(ts_sec: int) -> str:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    d = datetime.fromtimestamp(int(ts_sec), timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
    m = d.hour * 60 + d.minute
    if 480 <= m < 690:
        return "London"
    if 870 <= m < 1050:
        return "NY"
    return "off"


def _safe(x):
    return float(x) if x is not None and np.isfinite(x) else np.nan


def compute_features(o, h, l, c, t, *, ob: int, j: int, k: int, piv_i: int, piv_p: float, touch: int,
                     bull: bool, top: float, bot: float, entry: float, sl: float, atr: float,
                     pivots_opp: list | None = None, N: int = 3) -> dict:
    """t = bar open times in epoch seconds. pivots_opp = pivots on the liquidity side
    (bull: pivot lows, bear: pivot highs) for the sweep feature."""
    n = len(c)
    A = atr if atr > 0 else np.nan
    sg = 1.0 if bull else -1.0
    f: dict = {}
    rng = h[ob] - l[ob]
    body = abs(c[ob] - o[ob])
    up_w = h[ob] - max(o[ob], c[ob])
    lo_w = min(o[ob], c[ob]) - l[ob]
    f["ob_range_atr"] = rng / A
    f["ob_body_ratio"] = body / rng if rng > 0 else np.nan
    # proximal wick = side price comes back to (bull: upper), distal = invalidation side
    f["ob_prox_wick"] = (up_w if bull else lo_w) / rng if rng > 0 else np.nan
    f["ob_dist_wick"] = (lo_w if bull else up_w) / rng if rng > 0 else np.nan
    f["zone_h_atr"] = (top - bot) / A
    f["entry_mid"] = int(abs(entry - (top + bot) / 2) < 1e-12 * max(1.0, abs(entry)))
    f["risk_atr"] = abs(entry - sl) / A
    # displacement
    d1 = ob + 1
    f["disp1_body_atr"] = abs(c[d1] - o[d1]) / A
    f["disp1_range_atr"] = (h[d1] - l[d1]) / A
    f["disp1_body_pct"] = abs(c[d1] - o[d1]) / (h[d1] - l[d1]) if h[d1] > l[d1] else np.nan
    f["disp1_dir_ok"] = int((c[d1] > o[d1]) if bull else (c[d1] < o[d1]))
    f["disp_maxbody_atr"] = max(abs(c[x] - o[x]) for x in range(ob + 1, min(ob + 3, n))) / A
    nd = 0
    x = ob + 1
    while x < n and ((c[x] > o[x]) if bull else (c[x] < o[x])):
        nd += 1
        x += 1
    f["disp_n"] = nd
    e3 = min(ob + 4, n)
    f["impulse3_atr"] = ((np.max(h[ob + 1:e3]) - h[ob]) if bull else (l[ob] - np.min(l[ob + 1:e3]))) / A
    f["fvg_atr"] = ((l[ob + 2] - h[ob]) if bull else (l[ob] - h[ob + 2])) / A
    # structure / BOS
    f["bos_bars"] = j - ob
    f["bos_margin_atr"] = sg * (c[j] - piv_p) / A
    f["ob_to_bos_atr"] = ((piv_p - top) if bull else (bot - piv_p)) / A
    f["piv_age"] = j - piv_i
    f["leg_gap"] = k - ob  # 0 = OB candle is the leg extreme
    f["leg_ext_beyond_atr"] = max(0.0, (bot - l[k]) if bull else (h[k] - top)) / A
    f["opp_between"] = int(sum(1 for x in range(ob + 1, j + 1) if ((c[x] < o[x]) if bull else (c[x] > o[x]))))
    f["leg_len_atr"] = ((h[j] - l[k]) if bull else (h[k] - l[j])) / A
    f["ob_before_pivot"] = int(ob < piv_i)
    # prior chop
    for w in (10, 20):
        a = max(0, ob - w)
        ov = int(np.sum((l[a:ob] <= top) & (h[a:ob] >= bot)))
        f[f"chop{w}"] = ov
    a = max(0, ob - 20)
    f["range20_atr"] = (np.max(h[a:ob + 1]) - np.min(l[a:ob + 1])) / A if ob > a else np.nan
    # liquidity sweep by the leg extreme (untaken pivot within 50 bars taken by the leg, then BOS)
    sw = 0
    if pivots_opp:
        for (pi, pp) in pivots_opp:
            if pi >= k - N or pi < k - 50:
                continue
            if bull:
                if l[k] < pp and (pi + 1 >= k or np.min(l[pi + 1:k]) >= pp):
                    sw = 1
                    break
            else:
                if h[k] > pp and (pi + 1 >= k or np.max(h[pi + 1:k]) <= pp):
                    sw = 1
                    break
    f["sweep_leg"] = sw
    # touch / approach
    if touch is not None and 0 <= touch < n and touch > j:
        f["touch_bars"] = touch - ob
        f["touch_after_bos"] = touch - j
        seg_h = h[j:touch]
        seg_l = l[j:touch]
        if bull:
            xi = j + int(np.argmax(seg_h))
            run = (h[xi] - top) / A
        else:
            xi = j + int(np.argmin(seg_l))
            run = (bot - l[xi]) / A
        f["run_after_bos_atr"] = run
        f["approach_bars"] = touch - xi
        f["approach_speed"] = run / max(1, touch - xi)
        f["touch_range_atr"] = (h[touch] - l[touch]) / A
        f["touch_body_atr"] = abs(c[touch] - o[touch]) / A
        f["touch_toward"] = int((c[touch] < o[touch]) if bull else (c[touch] > o[touch]))
        f["touch_big"] = int(f["touch_range_atr"] >= 1.5)
        f["mom3_atr"] = (sg * (c[touch - 4] - c[touch - 1]) / A) if touch - 4 >= 0 else np.nan
        cnt = 0
        x = touch - 1
        while x > j and ((c[x] < o[x]) if bull else (c[x] > o[x])):
            cnt += 1
            x -= 1
        f["consec_toward"] = cnt
        f["prev_close_dist_atr"] = ((c[touch - 1] - top) if bull else (bot - c[touch - 1])) / A
        f["gap_entry"] = int((o[touch] <= entry) if bull else (o[touch] >= entry))
        f["touch_open_inside"] = int(o[touch] <= top and o[touch] >= bot)
        f["touch_close_through"] = int((c[touch] < bot) if bull else (c[touch] > top))
        f["touch_session"] = session_label(t[touch])
        f["touch_dow"] = int(((int(t[touch]) // 86400) + 3) % 7)
    return f


def fill_outcome(o, h, l, c, *, touch: int, bull: bool, entry: float, sl: float, rr: float = 2.0,
                 max_bars: int = 300) -> tuple[str, int, float]:
    """'Did the OB hold?' on TF bars: limit at entry from the touch bar; after fill, first of
    SL / +rr R (SL first on ambiguous bars; on the fill bar TP only if CLOSE beyond it).
    Returns (outcome in tp|sl|nofill|open, bars to exit, MFE in R before exit)."""
    n = len(c)
    risk = abs(entry - sl)
    if risk <= 0:
        return "invalid", 0, np.nan
    tp = entry + rr * risk if bull else entry - rr * risk
    f = None
    for x in range(touch, min(n, touch + max_bars)):
        if (l[x] <= entry) if bull else (h[x] >= entry):
            f = x
            break
    if f is None:
        return ("nofill" if touch + max_bars <= n else "open"), 0, np.nan
    mfe = 0.0
    for x in range(f, min(n, f + max_bars)):
        if (l[x] <= sl) if bull else (h[x] >= sl):
            return "sl", x - f, mfe
        ref = c[x] if x == f else (h[x] if bull else l[x])
        if (ref >= tp) if bull else (ref <= tp):
            return "tp", x - f, rr
        fav = ((h[x] - entry) if bull else (entry - l[x])) / risk if x > f else 0.0
        mfe = max(mfe, fav)
    return "open", 0, mfe


def textbook_flags(f: dict) -> dict:
    g = lambda k: f.get(k, np.nan)  # noqa: E731
    out = {
        "T1_displacement": g("disp_maxbody_atr") >= 1.0,
        "T2_fvg": g("fvg_atr") >= 0.25,
        "T3_bos_fast": g("bos_bars") <= 10,
        "T4_bos_margin": g("bos_margin_atr") >= 0.10,
        "T5_origin": g("leg_ext_beyond_atr") <= 0.10,
        "T6_not_chop": g("chop10") <= 5,
        "T7_body": g("ob_body_ratio") >= 0.25,
        "T8_size": (g("zone_h_atr") >= 0.2) and (g("zone_h_atr") <= 2.5),
    }
    out = {k: int(bool(v)) for k, v in out.items()}
    out["tb_fails"] = int(sum(1 - v for v in out.values()))
    return out
