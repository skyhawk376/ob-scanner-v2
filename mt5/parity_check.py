#!/usr/bin/env python3
"""Contrôle de parité EA MT5 <-> moteur v3 « Kasper ».

Deux modes :

1) --replay (défaut) : rejoue en Python la logique *streaming* de OB_Kasper_v3.mq5
   (mêmes étapes, même ordre d'événements : bougies LTF clôturées puis clôture HTF,
   détection à la clôture de la bougie OB+3 sur une fenêtre de --hist bougies,
   indices relatifs à l'OB, machine à états ACTIVE / WINDOW / WAIT_OUT) sur le cache M1,
   et la compare zone par zone avec app.v3.detect + app.v3.sim (le moteur de prod).

2) --ea-csv FICHIER : compare le CSV de zones écrit par l'EA (MQL5/Files/OBK3_zones_*.csv)
   avec le zones.csv de scripts/v3/backtest.py (même symbole / TF / période).

  /tmp/obv/bin/python mt5/parity_check.py --symbol EURUSD --tf H1 --start 2026-01-01 --end 2026-07-01
  /tmp/obv/bin/python mt5/parity_check.py --ea-csv OBK3_zones_EURUSD_H1.csv \
        --py-csv data/backtest/v3_sanity/zones.csv --symbol EURUSD --tf H1
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "v3"))
from app.v3 import params as P  # noqa: E402
from app.v3.detect import detect_zones, in_session  # noqa: E402
from app.v3.patterns import reversal_kind  # noqa: E402
from app.v3.sim import simulate_zone  # noqa: E402

M1 = ROOT / "data/cache/strategy_research/m1"


# ------------------------------------------------------------------ port 1:1 de l'EA
def ea_atr(h, l, c, n):
    """ATR Wilder sur la fenêtre (graine = moyenne des n premiers TR), comme AtrAt() de l'EA."""
    L = len(h)
    out = np.full(L, np.nan)
    if L < n:
        return out
    tr = np.empty(L)
    tr[0] = h[0] - l[0]
    for k in range(1, L):
        tr[k] = max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1]))
    out[n - 1] = tr[:n].mean()
    for k in range(n, L):
        out[k] = (out[k - 1] * (n - 1) + tr[k]) / n
    return out


def ea_is_pivot(x, p, n, high):
    if p - n < 0 or p + n >= len(x):
        return False
    for q in range(p - n, p + n + 1):
        if q == p:
            continue
        if high and x[q] >= x[p]:
            return False
        if not high and x[q] <= x[p]:
            return False
    return True


def ea_detect(o, h, l, c, times, tf, atr_len=P.ATR_LEN):
    """Détection sur la fenêtre se terminant à la bougie D = OB+3 (dernier indice)."""
    n = len(h)
    i = n - 1 - P.IMPULSE_BARS
    if i < atr_len:
        return []
    a = ea_atr(h, l, c, atr_len)
    av = a[i]
    if not np.isfinite(av) or av <= 0:
        return []
    out = []
    for bull in (True, False):
        if bull and not (c[i] < o[i] and c[i + 1] > o[i + 1]):
            continue
        if not bull and not (c[i] > o[i] and c[i + 1] < o[i + 1]):
            continue
        last = i + P.IMPULSE_BARS
        if bull and h[i + 1:last + 1].max() - h[i] < P.IMPULSE_ATR * av:
            continue
        if not bull and l[i] - l[i + 1:last + 1].min() < P.IMPULSE_ATR * av:
            continue
        k_f = None
        for k in range(i + 1, last):
            if (bull and l[k + 1] > h[k - 1]) or (not bull and h[k + 1] < l[k - 1]):
                k_f = k
                break
        if k_f is None:
            continue
        # étoiles statiques
        hs = [p for p in range(0, i - P.PIVOT_N + 1) if ea_is_pivot(h, p, P.PIVOT_N, True)]
        ls = [p for p in range(0, i - P.PIVOT_N + 1) if ea_is_pivot(l, p, P.PIVOT_N, False)]
        trend = 0
        if len(hs) >= 2 and len(ls) >= 2:
            if h[hs[-1]] > h[hs[-2]] and l[ls[-1]] > l[ls[-2]]:
                trend = 1
            elif h[hs[-1]] < h[hs[-2]] and l[ls[-1]] < l[ls[-2]]:
                trend = -1
        liq = False
        s0 = i - P.SWEEP_WIN + 1
        piv = ls if bull else hs
        if s0 > 0:
            for p in piv:
                if not (p >= i - P.LIQ_LOOKBACK and p < s0 and p + P.PIVOT_N <= i):
                    continue
                if bull:
                    ok = all(l[q] >= l[p] for q in range(p + 1, s0)) and min(l[s0:i + 1]) < l[p]
                else:
                    ok = all(h[q] <= h[p] for q in range(p + 1, s0)) and max(h[s0:i + 1]) > h[p]
                if ok:
                    liq = True
                    break
        out.append(dict(bull=bull, ob_time=times[i], lo=l[i], hi=h[i], atr=av,
                        armed_rel=k_f + 2 - i, trend=trend == (1 if bull else -1), liq=liq,
                        sess=in_session(times[i], tf), ext_hi=max(h[i], h[i + 1:last].max()),
                        ext_lo=min(l[i], l[i + 1:last].min())))
    return out


class EaZone:
    """Même machine à états que la struct CZone de l'EA."""

    def __init__(self, d, tf, min_stars):
        self.__dict__.update(d)
        self.tf, self.min_stars = tf, min_stars
        self.prox = self.hi if self.bull else self.lo
        self.dist = self.lo if self.bull else self.hi
        self.sl = self.dist - P.SL_BUFFER_ATR * self.atr if self.bull else self.dist + P.SL_BUFFER_ATR * self.atr
        self.ext = self.ext_hi if self.bull else self.ext_lo   # barres OB+1..OB+2 (D rejouée ensuite)
        self.cur = P.IMPULSE_BARS          # indice relatif de la bougie HTF en cours
        self.phase, self.pos = "ACTIVE", self.armed_rel
        self.n_touch, self.state, self.trade = 0, None, None
        self.touches = []

    def stars(self):
        if self.bull:
            fib = self.hi <= self.lo + P.FIB_LEVEL * (self.ext - self.lo)
        else:
            fib = self.lo >= self.hi - P.FIB_LEVEL * (self.hi - self.ext)
        st = dict(tendance=self.trend, liquidite=self.liq, vierge=self.n_touch == 1,
                  fibo=bool(fib), session=self.sess)
        return st, sum(st.values())

    def on_ltf(self, bo, step, ltf_step, j, lo, lh, ll, lc, ltime, past):
        if self.state:
            return
        if self.phase == "ACTIVE":
            if self.cur < self.pos or self.cur > P.MAX_AGE_BARS:
                return
            hit = ll[j] <= self.prox if self.bull else lh[j] >= self.prox
            if not hit:
                return
            self.n_touch += 1
            st, sc = self.stars()
            self.touches.append(sc)
            if sc >= self.min_stars:
                self.phase, self.t_rel, self.win_end, self.j_start = "WINDOW", self.cur, bo + P.WINDOW_BARS * step, ltime[j]
            else:
                self.phase, self.pos = "WAIT_OUT", self.cur + 1
                return
        if self.phase == "WINDOW":
            if ltime[j] + ltf_step > self.win_end:
                self.phase, self.pos = "WAIT_OUT", (self.cur if bo >= self.win_end else self.cur + 1)
                return
            if ltime[j] < self.j_start or j < 1:
                return
            a = self.atr
            reach = ll[j] <= self.prox + P.AT_ZONE_ATR * a if self.bull else lh[j] >= self.prox - P.AT_ZONE_ATR * a
            inside = (lc[j] > self.sl and lc[j] > self.dist) if self.bull else (lc[j] < self.sl and lc[j] < self.dist)
            if reach and inside:
                kind = reversal_kind(self.bull, lo[j - 1], lc[j - 1], lo[j], lh[j], ll[j], lc[j])
                if kind:
                    self.trade = dict(trigger=kind, entry_ts=ltime[j] + ltf_step, entry=lc[j], touch_n=self.n_touch)
                    self.state = "missed" if past else "trade"

    def on_htf_close(self, h, l, c):
        if self.state:
            return
        r = self.cur
        beyond = c < self.dist if self.bull else c > self.dist
        if self.phase == "ACTIVE" and r >= self.pos:
            if r > P.MAX_AGE_BARS:
                self.state = "expired"
            elif beyond:
                self.state = "invalidated"
            elif r >= P.MAX_AGE_BARS:
                self.state = "expired"
        elif self.phase == "WINDOW":
            if beyond:
                self.state = "invalidated"
            elif r >= self.t_rel + P.WINDOW_BARS - 1:
                self.phase, self.pos = "WAIT_OUT", r + 1
        elif self.phase == "WAIT_OUT" and r >= self.pos:
            outside = l > self.prox if self.bull else h < self.prox
            if beyond:
                self.state = "invalidated"
            elif outside:
                self.phase, self.pos = "ACTIVE", r + 1
        if self.bull:
            self.ext = max(self.ext, h)
        else:
            self.ext = min(self.ext, l)
        self.cur += 1


def ea_replay(htf, ltf, tf, start, hist, min_stars):
    o, h, l, c = (htf[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t = htf.index
    lo, lh, ll, lc = (ltf[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    lt = ltf.index
    step = pd.Timedelta(minutes=P.TF_MIN[tf])
    lstep = pd.Timedelta(minutes=P.TF_MIN[P.LOWER_TF[tf]])
    jb = np.searchsorted(lt, t)                 # premier LTF de chaque bougie HTF
    je = np.searchsorted(lt, t + step)
    zones, live = [], []
    b0 = max(int(np.searchsorted(t, start)), hist)
    for b in range(b0, len(t)):
        for j in range(jb[b], je[b]):           # 1) bougies LTF clôturées
            for z in live:
                z.on_ltf(t[b], step, lstep, j, lo, lh, ll, lc, lt, False)
        for z in live:                          # 2) clôture HTF
            z.on_htf_close(h[b], l[b], c[b])
        live = [z for z in live if not z.state]
        s = b - hist + 1                        # 3) détection (OB = b-3) + rattrapage de D
        for d in ea_detect(o[s:b + 1], h[s:b + 1], l[s:b + 1], c[s:b + 1], t[s:b + 1], tf):
            z = EaZone(d, tf, min_stars)
            for j in range(jb[b], je[b]):
                z.on_ltf(t[b], step, lstep, j, lo, lh, ll, lc, lt, True)
            z.on_htf_close(h[b], l[b], c[b])
            zones.append(z)
            if not z.state:
                live.append(z)
    return zones


def resample(m1, tf):
    rule = {"M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h", "D": "1D"}[tf]
    if tf == "M1":
        return m1
    return m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def replay_mode(a):
    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    m1 = pd.read_parquet(M1 / f"{a.symbol}_M1.parquet")[["open", "high", "low", "close"]].astype(float)
    m1.index = pd.DatetimeIndex(m1.index).tz_convert("UTC").as_unit("ns")
    warm = pd.Timedelta(minutes=P.TF_MIN[a.tf] * (a.hist + 50) * 2)
    m1 = m1[(m1.index >= start - warm) & (m1.index < end)]
    htf = resample(m1, a.tf)
    lt = P.LOWER_TF[a.tf]
    ltf = resample(m1, lt) if lt != "M1" else m1
    # moteur v3 (prod)
    pyz = {}
    for z in detect_zones(htf, a.tf, a.symbol):
        if pd.Timestamp(z["ts_ob"]) < start + pd.Timedelta(minutes=P.TF_MIN[a.tf] * 4):
            continue
        r = simulate_zone(z, htf, ltf)
        pyz[(z["ts_ob"], z["direction"])] = (z, r)
    ea = ea_replay(htf, ltf, a.tf, start + pd.Timedelta(minutes=P.TF_MIN[a.tf] * 4) + pd.Timedelta(minutes=P.TF_MIN[a.tf] * 3), a.hist, P.MIN_STARS)
    eaz = {(pd.Timestamp(z.ob_time).isoformat(), "bull" if z.bull else "bear"): z for z in ea}
    keys_p, keys_e = set(pyz), set(eaz)
    common = keys_p & keys_e
    print(f"{a.symbol} {a.tf} {a.start}..{a.end}  zones v3={len(keys_p)} EA={len(keys_e)} communes={len(common)}")
    print("  seulement v3:", sorted(keys_p - keys_e)[:5], " seulement EA:", sorted(keys_e - keys_p)[:5])
    c = Counter()
    for k in sorted(common):
        z, r = pyz[k]
        e = eaz[k]
        c["stars_static_ok"] += (z["star_trend"] == e.trend and z["star_liquidity"] == e.liq and z["star_session"] == e.sess)
        c["atr_close"] += abs(z["atr"] - e.atr) <= 1e-6 * max(1.0, z["atr"])
        pt = r["trade"]
        if pt is None and e.trade is None:
            c["no_trade_both"] += 1
            ps = r["state"]
            es = e.state or {"ACTIVE": "active", "WINDOW": "touched", "WAIT_OUT": "waiting"}[e.phase]
            c["state_ok" if ps == es else "state_diff"] += 1
            if ps != es and c["state_diff"] <= 5:
                print("   état différent", k, "v3:", ps, r["n_touch"], "EA:", es, e.n_touch)
        elif pt is not None and e.trade is not None:
            same = (pd.Timestamp(pt["entry_ts"]) == e.trade["entry_ts"] and pt["trigger"] == e.trade["trigger"])
            c[("trade_same" if same else "trade_diff") + ("_missed" if e.state == "missed" else "")] += 1
            if not same and c["trade_diff"] <= 5:
                print("   trade différent", k, pt["entry_ts"], pt["trigger"], "EA:", e.trade)
        elif pt is not None:
            c["trade_only_v3"] += 1
            if c["trade_only_v3"] <= 5:
                print("   trade seulement v3", k, pt["entry_ts"], pt["trigger"], "EA:", e.state, e.phase, e.n_touch)
        else:
            c["trade_only_EA"] += 1
            if c["trade_only_EA"] <= 5:
                print("   trade seulement EA", k, e.trade, "v3:", r["state"], r["n_touch"])
    for k, v in sorted(c.items()):
        print(f"  {k:24s} {v}")
    n_tr_p = sum(1 for z, r in pyz.values() if r["trade"])
    n_tr_e = sum(1 for z in ea if z.state == "trade")
    n_miss = sum(1 for z in ea if z.state == "missed")
    print(f"  trades v3={n_tr_p}  trades EA={n_tr_e}  (+{n_miss} 'missed' = déclencheur dans la bougie OB+3, "
          "déjà passée au moment où l'EA connaît la zone)")


def csv_mode(a):
    ea = pd.read_csv(a.ea_csv, sep=";")
    py = pd.read_csv(a.py_csv)
    py = py[(py.symbol == a.py_symbol or a.symbol) & (py.tf == a.tf)] if "symbol" in py else py
    py = py[(py.symbol == (a.py_symbol or a.symbol)) & (py.tf == a.tf)]
    ea["key"] = pd.to_datetime(ea.ts_ob_utc, utc=True).astype(str) + "|" + ea.dir
    py["key"] = pd.to_datetime(py.ts_ob, utc=True).astype(str) + "|" + py.dir
    lo, hi = pd.to_datetime(ea.ts_ob_utc, utc=True).min(), pd.to_datetime(ea.ts_ob_utc, utc=True).max()
    py = py[(pd.to_datetime(py.ts_ob, utc=True) >= lo) & (pd.to_datetime(py.ts_ob, utc=True) <= hi)]
    m = ea.merge(py, on="key", how="outer", suffixes=("_ea", "_py"), indicator=True)
    print(m["_merge"].value_counts().to_string())
    both = m[m._merge == "both"]
    t_ea = both.trigger_ea.notna() if "trigger_ea" in both else both.trigger.notna()
    print("zones communes:", len(both))
    if "entry_ts" in py:
        same = (pd.to_datetime(both.entry_utc, utc=True, errors="coerce") == pd.to_datetime(both.entry_ts, utc=True, errors="coerce"))
        print("trades EA:", int(t_ea.sum()), " trades v3:", int(both.entry_ts.notna().sum()),
              " même heure d'entrée:", int(same.sum()))
    out = Path(a.ea_csv).with_suffix(".compare.csv")
    m.to_csv(out, index=False)
    print("détail ->", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--py-symbol", default=None, help="nom du symbole dans zones.csv si différent (ex. NAS100)")
    ap.add_argument("--tf", default="H1")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-01")
    ap.add_argument("--hist", type=int, default=1000, help="= input InpHistoryBars de l'EA")
    ap.add_argument("--ea-csv")
    ap.add_argument("--py-csv", default=str(ROOT / "data/backtest/v3_sanity/zones.csv"))
    a = ap.parse_args()
    csv_mode(a) if a.ea_csv else replay_mode(a)
