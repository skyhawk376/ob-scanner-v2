"""v3 zone lifecycle + trade simulation (identical code for live and backtest).

simulate_zone(zone, htf, ltf, now) replays the zone from its arming bar:
  active ──touch──▶ touched (window = 3 zone-TF bars for a LTF reversal candle)
     ▲                 │ trigger → trade (entered → be → tp | sl | be_exit)
     │ leave zone      │ no trigger → waiting (re-touch only after price left the zone)
  waiting ◀────────────┘
  any non-trade state ──zone-TF close beyond distal──▶ invalidated ; too old ──▶ expired
Stateless: the live service calls it every cycle on the cached candles and diffs the
resulting `events` against what was already notified (SQLite claim table).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import params as P
from .costs import costs, cost_r
from .patterns import reversal_kind

TERMINAL = ("tp", "sl", "be_exit", "invalidated", "expired")


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _iso(x) -> str:
    return _ts(x).isoformat()


def norm_index(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """UTC, nanosecond DatetimeIndex (cache files may come back in s/ms/us units and
    searchsorted with a ns Timestamp would raise 'Cannot losslessly convert units')."""
    if df is None or not len(df):
        return df
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    if str(idx.dtype) != "datetime64[ns, UTC]":
        idx = idx.as_unit("ns")
    if idx is df.index:
        return df
    out = df.copy()
    out.index = idx
    return out


def _first(mask: np.ndarray, start: int, stop: int) -> int | None:
    if start >= stop:
        return None
    seg = mask[start:stop]
    k = int(np.argmax(seg)) if len(seg) else 0
    return start + k if len(seg) and seg[k] else None


def stars_at(zone: dict, h, l, ob_i: int, t: int, virgin: bool) -> dict[str, bool]:
    """Five stars evaluated at bar t (exclusive) — Fibo uses the leg OB → extreme before t."""
    bull = zone["direction"] == "bull"
    lo, hi = zone["low"], zone["high"]
    s = max(ob_i + 1, 0)
    if bull:
        ext = float(np.max(h[s:t])) if t > s else hi
        ext = max(ext, hi)
        eq = lo + P.FIB_LEVEL * (ext - lo)
        fib = hi <= eq
    else:
        ext = float(np.min(l[s:t])) if t > s else lo
        ext = min(ext, lo)
        eq = hi - P.FIB_LEVEL * (hi - ext)
        fib = lo >= eq
    return {
        "tendance": bool(zone.get("star_trend")),
        "liquidite": bool(zone.get("star_liquidity")),
        "vierge": bool(virgin),
        "fibo": bool(fib),
        "session": bool(zone.get("star_session")),
        "_fib_eq": float(eq),
    }


def score_of(st: dict) -> int:
    return sum(1 for k in ("tendance", "liquidite", "vierge", "fibo", "session") if st.get(k))


def _trade(zone: dict, ltf: pd.DataFrame, j0: int, entry: float, sl: float, bull: bool,
           nc_ltf: int, ltf_step: pd.Timedelta) -> dict[str, Any]:
    """Manage a market entry at LTF bar j0 close: SL / +1R→BE / TP +2R, no time stop.
    Conservative same-bar rule: SL before TP/BE. Spread: stops trigger at mid ± half spread."""
    sym, group = zone["symbol"], zone.get("group", "")
    risk = abs(entry - sl)
    sp, _, _ = costs(sym, entry, group)
    half = sp / 2.0
    sgn = 1.0 if bull else -1.0
    tp = entry + sgn * P.TP_R * risk
    be_lvl = entry + sgn * P.BE_AT_R * risk
    h = ltf["high"].to_numpy(float)
    l = ltf["low"].to_numpy(float)
    idx = ltf.index
    s, e = j0 + 1, nc_ltf
    if bull:
        sl_hit = l <= sl + half
        be_hit = h >= be_lvl
        tp_hit = h >= tp + half
        be_stop = l <= entry + half
    else:
        sl_hit = h >= sl - half
        be_hit = l <= be_lvl
        tp_hit = l <= tp - half
        be_stop = h >= entry - half
    tr: dict[str, Any] = {
        "entry": entry, "sl": sl, "tp": tp, "be_level": be_lvl, "risk": risk,
        "entry_ts": _iso(idx[j0] + ltf_step), "status": "open", "exit": None,
        "exit_ts": None, "be_ts": None, "r_gross": None, "r_net": None,
    }
    big = 1 << 62
    s1 = _first(sl_hit, s, e)
    b1 = _first(be_hit, s, e)
    t1 = _first(tp_hit, s, e)
    S, B, T = (s1 if s1 is not None else big), (b1 if b1 is not None else big), (t1 if t1 is not None else big)

    def close(kind: str, j: int, r: float) -> None:
        tr.update(status="closed", exit=kind, exit_ts=_iso(idx[j] + ltf_step), r_gross=r,
                  r_net=round(r - cost_r(sym, entry, risk, group, stop_exit=kind != "tp"), 4))

    if S == big and B == big:
        return tr
    if S <= B and S <= T:
        close("sl", S, -1.0)
        return tr
    if T <= B:  # TP on the very bar that reached +1R
        close("tp", T, P.TP_R)
        return tr
    tr["be_ts"] = _iso(idx[B] + ltf_step)
    tr["status"] = "be"
    s2 = _first(be_stop, B + 1, e)
    t2 = _first(tp_hit, B + 1, e)
    S2, T2 = (s2 if s2 is not None else big), (t2 if t2 is not None else big)
    if S2 == big and T2 == big:
        return tr
    if S2 <= T2:
        close("be_exit", S2, 0.0)
    else:
        close("tp", T2, P.TP_R)
    return tr


def simulate_zone(zone: dict, htf: pd.DataFrame, ltf: pd.DataFrame | None,
                  now: pd.Timestamp | None = None) -> dict[str, Any]:
    htf = norm_index(htf)
    ltf = norm_index(ltf)
    tf = zone["tf"]
    bull = zone["direction"] == "bull"
    prox = zone["high"] if bull else zone["low"]
    dist = zone["low"] if bull else zone["high"]
    a_tr = zone["atr"]
    step = pd.Timedelta(minutes=P.TF_MIN[tf])
    ltf_tf = P.LOWER_TF[tf]
    ltf_step = pd.Timedelta(minutes=P.TF_MIN[ltf_tf])
    if len(htf):
        oi = int(np.searchsorted(htf.index, _ts(zone["ts_ob"])))
        htf = htf.iloc[max(oi, 0): oi + P.MAX_AGE_BARS + 2]
        if ltf is not None and len(ltf) and len(htf):
            ltf = ltf.iloc[int(np.searchsorted(ltf.index, htf.index[0])):]
    idx = htf.index
    h = htf["high"].to_numpy(float)
    l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float)
    n = len(htf)
    now_ts = _ts(now) if now is not None else (idx[-1] + step if n else _ts("2100-01-01"))
    nc = int(np.searchsorted(idx, now_ts - step, side="right")) if n else 0  # closed bars
    res: dict[str, Any] = {"state": "active", "touches": [], "trade": None, "events": [],
                           "invalidated_ts": None, "expired_ts": None, "ltf": ltf_tf,
                           "last_close": float(c[-1]) if n else None, "n_touch": 0}
    ob_i = int(np.searchsorted(idx, _ts(zone["ts_ob"]))) if n else 0
    if ob_i >= n or (ob_i < n and idx[ob_i] != _ts(zone["ts_ob"])):
        ob_i = ob_i - 1  # OB bar trimmed out of the cache: leg starts at the first bar we have
    if n == 0 or not zone.get("armed_ts"):
        res["stars"] = stars_at(zone, h, l, ob_i, n, True)
        res["score"] = score_of(res["stars"])
        return res
    a = int(np.searchsorted(idx, _ts(zone["armed_ts"])))
    touch = (l <= prox) if bull else (h >= prox)
    outside = (l > prox) if bull else (h < prox)
    beyond = (c < dist) if bull else (c > dist)
    exp_i = (ob_i + P.MAX_AGE_BARS) if ob_i >= 0 else (a + P.MAX_AGE_BARS)

    if ltf is not None and len(ltf):
        lo_ = ltf["open"].to_numpy(float)
        lh = ltf["high"].to_numpy(float)
        ll = ltf["low"].to_numpy(float)
        lc = ltf["close"].to_numpy(float)
        lidx = ltf.index
        nc_ltf = int(np.searchsorted(lidx, now_ts - ltf_step, side="right"))
    else:
        lidx = None
        nc_ltf = 0

    sl = (dist - P.SL_BUFFER_ATR * a_tr) if bull else (dist + P.SL_BUFFER_ATR * a_tr)
    pos, rearmed, n_touch = a, True, 0
    last_stars = stars_at(zone, h, l, ob_i, n, True)
    state = "active"
    while pos < n:
        inv = _first(beyond, pos, nc)
        if not rearmed:
            o = _first(outside, pos, n)
            if o is None:
                if inv is not None:
                    state = "invalidated"
                    res["invalidated_ts"] = _iso(idx[inv] + step)
                break
            if inv is not None and inv < o:
                state = "invalidated"
                res["invalidated_ts"] = _iso(idx[inv] + step)
                break
            pos, rearmed = o + 1, True
            continue
        t = _first(touch, pos, n)
        if exp_i < nc and (t is None or exp_i < t) and (inv is None or exp_i < inv):
            state = "expired"
            res["expired_ts"] = _iso(idx[min(exp_i, n - 1)] + step)
            break
        if t is None or (inv is not None and inv < t):
            if inv is not None:
                state = "invalidated"
                res["invalidated_ts"] = _iso(idx[inv] + step)
            break
        # ---- touch at HTF bar t
        n_touch += 1
        st = stars_at(zone, h, l, ob_i, t, n_touch == 1)
        sc = score_of(st)
        last_stars = st
        bar_open = idx[t]
        win_end = bar_open + P.WINDOW_BARS * step
        inv_after = _first(beyond, t, nc)
        inv_time = (idx[inv_after] + step) if inv_after is not None else None
        touch_ts = bar_open
        j_start = None
        if lidx is not None:
            js = int(np.searchsorted(lidx, bar_open))
            je = int(np.searchsorted(lidx, bar_open + step))
            tm = (ll[js:je] <= prox) if bull else (lh[js:je] >= prox)
            if tm.any():
                j_start = js + int(np.argmax(tm))
                touch_ts = lidx[j_start]
            else:
                j_start = js
        tinfo = {"n": n_touch, "ts": _iso(touch_ts), "score": sc,
                 "stars": {k: v for k, v in st.items() if not k.startswith("_")},
                 "fib_eq": st["_fib_eq"], "window_end": _iso(win_end), "trigger": None}
        res["touches"].append(tinfo)
        if sc >= P.MIN_STARS and n_touch <= P.MAX_TOUCH_ALERTS:
            res["events"].append({"key": f"touch{n_touch}", "kind": "touch", "ts": tinfo["ts"],
                                  "score": sc, "stars": tinfo["stars"]})
        trig = None
        ltf_missing = False
        if sc >= P.MIN_STARS:
            limit_t = win_end if inv_time is None else min(win_end, inv_time)
            if lidx is None or j_start is None:
                ltf_missing = True
            else:
                j = max(j_start, 1)
                while j < nc_ltf:
                    close_t = lidx[j] + ltf_step
                    if close_t > limit_t:
                        break
                    if lidx[j] >= bar_open:
                        reach = (ll[j] <= prox + P.AT_ZONE_ATR * a_tr) if bull else (lh[j] >= prox - P.AT_ZONE_ATR * a_tr)
                        inside = (lc[j] > sl and lc[j] > dist) if bull else (lc[j] < sl and lc[j] < dist)
                        if reach and inside:
                            kind = reversal_kind(bull, lo_[j - 1], lc[j - 1], lo_[j], lh[j], ll[j], lc[j])
                            if kind:
                                trig = (j, kind)
                                break
                    j += 1
                if trig is None and (len(lidx) == 0 or lidx[-1] + ltf_step < min(limit_t, now_ts)):
                    ltf_missing = bool(win_end <= now_ts)
        if trig is not None:
            j, kind = trig
            entry = float(lc[j])
            tinfo["trigger"] = kind
            tr = _trade(zone, ltf, j, entry, sl, bull, nc_ltf, ltf_step)
            tr.update(trigger=kind, ltf=ltf_tf, score=sc, stars=tinfo["stars"], touch_n=n_touch)
            res["trade"] = tr
            res["events"].append({"key": "entry", "kind": "entry", "ts": tr["entry_ts"]})
            if tr["be_ts"]:
                res["events"].append({"key": "be", "kind": "be", "ts": tr["be_ts"]})
            if tr["status"] == "closed":
                res["events"].append({"key": "exit", "kind": "exit", "ts": tr["exit_ts"],
                                      "exit": tr["exit"], "r": tr["r_net"]})
                state = tr["exit"]
            else:
                state = "be" if tr["be_ts"] else "entered"
            break
        if ltf_missing:
            tinfo["ltf_missing"] = True
        if sc >= P.MIN_STARS and win_end > now_ts:
            state = "touched"  # live: still waiting for the LTF reversal candle
            break
        state = "waiting"
        rearmed = False
        if sc >= P.MIN_STARS:
            nxt = int(np.searchsorted(idx, win_end))
            if inv_after is not None and inv_after < nxt:
                state = "invalidated"
                res["invalidated_ts"] = _iso(idx[inv_after] + step)
                break
            pos = max(nxt, t + 1)
        else:
            pos = t + 1
    res["state"] = state
    res["n_touch"] = n_touch
    if state == "active":
        last_stars = stars_at(zone, h, l, ob_i, n, True)
    res["stars"] = {k: v for k, v in last_stars.items() if not k.startswith("_")}
    res["fib_eq"] = last_stars["_fib_eq"]
    res["score"] = score_of(last_stars)
    res["sl"] = sl
    return res
