#!/usr/bin/env python3
"""Reversal-candle entry triggers (PREREG_REVERSAL.md): detect triggers per zone, build orders, simulate (net + gross).
Output: results/events.parquet (orders), results/trades.parquet (filled trades, net costs + zero-cost gross)."""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "strategy_research"))
import common as C  # noqa: E402

RES = HERE / "results"; RES.mkdir(exist_ok=True)
ZONES = ROOT / "scripts/ob_shape/results/hist_zones.parquet"
RULE = {"M1": None, "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}
DUR = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}
LTF = {"M5": "M1", "M15": "M5", "M30": "M15", "H1": "M15", "H4": "H1"}
NS_MIN = 60_000_000_000
LAT = 3 * NS_MIN
BUF = 0.05
W = {"1h": 60 * NS_MIN, "3h": 180 * NS_MIN}


def tf_bars(sym, tf):
    if tf == "M1":
        A = C.arrays(sym)
        op = A["t"]; o, h, l, c = A["o"], A["h"], A["l"], A["c"]
    else:
        b = C.resample(sym, RULE[tf]); b = b[b.high >= b.low]
        op = b.index.as_unit("ns").asi8.astype(np.int64)
        o, h, l, c = (b[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    return dict(op=op, cl=op + DUR[tf] * NS_MIN, o=o, h=h, l=l, c=c)


def frac_pivots(h):
    n = len(h); p = np.zeros(n, bool)
    if n >= 5:
        m = h[2:-2]
        p[2:-2] = (m > h[1:-3]) & (m > h[:-4]) & (m > h[3:-1]) & (m > h[4:])
    return p


def last_eligible(B, ib0, t0, Wn):
    n = len(B["op"]); k_end = ib0
    while k_end + 1 < n and B["cl"][k_end + 1] <= t0 + Wn:
        k_end += 1
    return k_end


def bull_view(B, sl_, s):
    if s > 0:
        return B["o"][sl_], B["h"][sl_], B["l"][sl_], B["c"][sl_]
    return -B["o"][sl_], -B["l"][sl_], -B["h"][sl_], -B["c"][sl_]


def scan_candles(B, s, ib0, t0, top, bot, atr):
    """First T1/T2/T4 trigger (bull space) among eligible candles before invalidation: (k, extreme_low, close)."""
    k_end = last_eligible(B, ib0, t0, W["3h"])
    sl_ = slice(max(ib0 - 1, 0), k_end + 1)
    o, h, l, c = bull_view(B, sl_, s)
    off = sl_.start
    out = {"T1": None, "T2": None, "T4": None}
    for k in range(ib0, k_end + 1):
        j = k - off
        if l[j] <= top and c[j] > bot:
            if out["T1"] is None and j >= 1 and c[j] > o[j] and c[j - 1] < o[j - 1] and c[j] >= o[j - 1] \
                    and o[j] <= c[j - 1] + 0.05 * atr:
                out["T1"] = (k, min(l[j], l[j - 1]), c[j])
            rng = h[j] - l[j]
            if out["T2"] is None and rng > 0 and (min(o[j], c[j]) - l[j]) >= 2 * abs(c[j] - o[j]) \
                    and c[j] >= l[j] + rng * 2 / 3:
                out["T2"] = (k, l[j], c[j])
            if out["T4"] is None and c[j] > top:
                out["T4"] = (k, l[j], c[j])
        if c[j] < bot:  # invalidation: close beyond distal edge
            break
    return out


def scan_choch(B, s, ib0, t0, bot):
    k_end = last_eligible(B, ib0, t0, W["3h"])
    a = max(ib0 - 50, 0)
    _, h, l, c = bull_view(B, slice(a, k_end + 1), s)
    piv = frac_pivots(h)
    last = None; lo = np.inf
    for k in range(a, k_end + 1):
        j = k - a
        if j - 3 >= 0 and piv[j - 3]:      # pivot at j-3 confirmed by bar j-1
            last = h[j - 3]
        if k < ib0:
            continue
        lo = min(lo, l[j])
        if last is not None and c[j] > last and c[j] > bot:
            return (k, lo, c[j], last)
        if c[j] < bot:
            return None
    return None


def in_reg(k, ib0, tcl, t0, reg):
    return k == ib0 or tcl <= t0 + W[reg]


def zone_events(z, A, BT):
    s = 1 if z.direction == "bull" else -1
    top, bot, sl, entry = (z.top, z.bot, z.sl, z.entry) if s > 0 else (-z.bot, -z.top, -z.sl, -z.entry)
    atr = z.atr
    t_touch = pd.Timestamp(z.ts_touch).value
    i0 = np.searchsorted(A["t"], t_touch)
    i1 = np.searchsorted(A["t"], t_touch + DUR[z.tf] * NS_MIN)
    lm = A["l"][i0:i1] if s > 0 else -A["h"][i0:i1]
    hit = np.nonzero(lm <= top)[0]
    if not len(hit):
        return None, []
    m0 = i0 + hit[0]; t0 = int(A["t"][m0])
    ev = []
    for tv in ("same", "ltf"):
        tf = z.tf if tv == "same" else LTF[z.tf]
        B = BT[tf]
        ib0 = np.searchsorted(B["op"], t0, side="right") - 1
        for fam, r in scan_candles(B, s, ib0, t0, top, bot, atr).items():
            if r is None:
                continue
            k, clow, cpx = r; tcl = int(B["cl"][k])
            for reg in ("1h", "3h"):
                if not in_reg(k, ib0, tcl, t0, reg):
                    continue
                for slv in ("zone", "candle"):
                    ev.append(dict(cfg=f"{fam}|{tv}|{slv}|{reg}", fam=fam, t_active=tcl + LAT, etype="market",
                                   level=cpx, sl=sl if slv == "zone" else clow - BUF * atr, hold=reg, t_trig=tcl,
                                   trig_tf=tf, k=k, expiry=1))
        if tv == "ltf":
            r = scan_choch(B, s, ib0, t0, bot)
            if r is not None:
                k, lo, cpx, lev = r; tcl = int(B["cl"][k])
                for reg in ("1h", "3h"):
                    if not in_reg(k, ib0, tcl, t0, reg):
                        continue
                    for slv in ("zone", "candle"):
                        slp = sl if slv == "zone" else lo - BUF * atr
                        ev.append(dict(cfg=f"T3|close|{slv}|{reg}", fam="T3", t_active=tcl + LAT, etype="market",
                                       level=cpx, sl=slp, hold=reg, t_trig=tcl, trig_tf=tf, k=k, expiry=1))
                        exp = (t0 + W[reg] - (tcl + LAT)) / NS_MIN
                        if exp > 0:
                            ev.append(dict(cfg=f"T3|retest|{slv}|{reg}", fam="T3", t_active=tcl + LAT, etype="limit",
                                           level=lev, sl=slp, hold=reg, t_trig=tcl, trig_tf=tf, k=k, expiry=exp))
    # ---- T5 sweep & reclaim (M1 path; no distal-close invalidation)
    j_end = np.searchsorted(A["t"], t0 + W["3h"])
    lw = A["l"][m0:j_end] if s > 0 else -A["h"][m0:j_end]
    hw = A["h"][m0:j_end] if s > 0 else -A["l"][m0:j_end]
    sw = np.nonzero(lw < sl)[0]
    if len(sw):
        t_sw = int(A["t"][m0 + sw[0]])
        st = np.searchsorted(A["t"], t_sw + LAT) - m0
        rec = np.nonzero(hw[st:] >= entry)[0] if st < len(hw) else []
        if len(rec):
            mf = st + rec[0]; tfill = int(A["t"][m0 + mf])
            low = lw[:mf + 1].min()
            for reg in ("1h", "3h"):
                if tfill < t0 + W[reg]:
                    ev.append(dict(cfg=f"T5a|m1|sweep|{reg}", fam="T5", t_active=tfill, etype="stop", level=entry,
                                   sl=low - BUF * atr, hold=reg, t_trig=tfill, trig_tf="M1", k=-1,
                                   expiry=(t0 + W[reg] - tfill) / NS_MIN, t_sweep=t_sw))
        for tv in ("same", "ltf"):
            tf = z.tf if tv == "same" else LTF[z.tf]
            B = BT[tf]
            ib0 = np.searchsorted(B["op"], t0, side="right") - 1
            k = np.searchsorted(B["cl"], t_sw, side="right")
            n = len(B["op"])
            while k < n and (k == ib0 or B["cl"][k] <= t0 + W["3h"]):
                ck = B["c"][k] if s > 0 else -B["c"][k]
                if ck > bot:
                    tcl = int(B["cl"][k])
                    low = lw[:max(np.searchsorted(A["t"], tcl) - m0, 1)].min()
                    for reg in ("1h", "3h"):
                        if not in_reg(k, ib0, tcl, t0, reg):
                            continue
                        ev.append(dict(cfg=f"T5b|{tv}|sweep|{reg}", fam="T5", t_active=tcl + LAT, etype="market",
                                       level=ck, sl=low - BUF * atr, hold=reg, t_trig=tcl, trig_tf=tf, k=k,
                                       expiry=1, t_sweep=t_sw))
                    break
                k += 1
    # ---- T0 (prod) and info variant with 3-min latency
    for reg in ("1h", "3h"):
        ev.append(dict(cfg=f"T0|limit|zone|{reg}", fam="T0", t_active=t0, etype="limit", level=entry, sl=sl,
                       hold=reg, t_trig=t0, trig_tf=z.tf, k=-1, expiry=25 * 60))
        ev.append(dict(cfg=f"T0lat|limit|zone|{reg}", fam="T0lat", t_active=t0 + LAT, etype="limit", level=entry,
                       sl=sl, hold=reg, t_trig=t0, trig_tf=z.tf, k=-1, expiry=25 * 60))
    for e in ev:
        if s < 0:
            e["level"] = -e["level"]; e["sl"] = -e["sl"]
    return t0, ev


def run_sym(sym, Z):
    A = C.arrays(sym)
    BT = {tf: tf_bars(sym, tf) for tf in DUR}
    rows = []
    for zid, z in Z.iterrows():
        t0, ev = zone_events(z, A, BT)
        if t0 is None:
            continue
        for e in ev:
            e.update(zid=zid, sym=sym, t0=t0, side=1 if z.direction == "bull" else -1)
            rows.append(e)
    return rows


def simulate_events(ev, Z):
    ev = ev.copy()
    ev["tp_r"] = 2.0
    ev["hold_min"] = ev.hold.map({"1h": 60, "3h": 180})
    ev["expiry_min"] = ev.expiry
    ev["rid"] = np.arange(len(ev))
    g = C.simulate(ev, cost_mult=0.0).set_index("rid")
    n = C.simulate(ev, cost_mult=1.0)
    n["r_gross"] = n.rid.map(g.r_gross)      # zero-cost run of the same order (NaN if it would not fill at zero cost)
    n = n.join(Z[["tf", "direction", "top", "bot", "entry", "atr"]], on="zid")
    # prereg: trade skipped if the fill is already at/through the SL (gap/latency through the stop; a broker rejects it)
    n = n[n.side * (n.entry_px - n.sl) > 0].copy()
    n["cost_r"] = n.comm / n.risk
    n["hold_real_min"] = (n.t_exit - n.t_fill).dt.total_seconds() / 60
    return n


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    t_start = time.time()
    Z = pd.read_parquet(ZONES)
    with ProcessPoolExecutor(6) as ex:
        futs = {sym: ex.submit(run_sym, sym, g) for sym, g in Z.groupby("sym")}
        rows = []
        for sym, f in futs.items():
            rows += f.result(); print(sym, len(rows), f"{time.time() - t_start:.0f}s", flush=True)
    ev = pd.DataFrame(rows)
    for c in ("t_active", "t_trig", "t0", "t_sweep"):
        ev[c] = pd.to_datetime(ev[c], utc=True)
    ev.to_parquet(RES / "events.parquet")
    tr = simulate_events(ev, Z)
    tr.to_parquet(RES / "trades.parquet")
    print(len(ev), "events", len(tr), "trades", f"{time.time() - t_start:.0f}s")
