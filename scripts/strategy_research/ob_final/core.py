"""OB-final study core: long-history M1 loader, TF bars, OBX zone detection, two-stage simulator with management.
Conventions identical to common._sim (see common.py docstring); verified equal when management is off (selftest).
"""
from __future__ import annotations
import math, sys
from functools import lru_cache
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common  # noqa: E402

ROOT = common.ROOT
M1_DIR = common.M1_DIR
CACHE = ROOT / "data/cache/strategy_research/ob_final"; CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data/backtest/strategy_research/ob_final"; OUT.mkdir(parents=True, exist_ok=True)

GROUP = common.GROUP
ASSETS = list(GROUP)
INDICES = ["NAS100", "US500", "DAX"]
SPLIT = pd.Timestamp("2022-01-01", tz="UTC")
RECENT = pd.Timestamp("2025-07-01", tz="UTC")
END = pd.Timestamp("2026-09-30 21:00", tz="UTC")
WARMUP_DAYS = 120
DELAY_MIN = 3

# swap: annual rate on price, charged per calendar day in trade, (long, short); both sides pay (conservative)
SWAP = {"FOREX": (0.015, 0.015), "METALS": (0.073, 0.0365), "INDICES": (0.06, 0.02), "CRYPTO": (0.10, 0.03)}

def costs(sym, price):
    return common.costs(sym, price)

# ------------------------------------------------------------------------------------------------ data
def _files(sym):
    if GROUP[sym] == "CRYPTO":
        return [M1_DIR / f"{sym}_M1_2017_2022.parquet", M1_DIR / f"{sym}_M1.parquet"]
    fs = [M1_DIR / f"{sym}_M1_2015_2022.parquet"]
    if sym == "XAUUSD":
        fs.append(M1_DIR / "XAUUSD_M1_2019_2022.parquet")
    fs.append(M1_DIR / f"{sym}_M1.parquet")
    return fs

@lru_cache(maxsize=2)
def load_m1(sym: str) -> pd.DataFrame:
    p = CACHE / f"{sym}_M1_long.parquet"
    if p.exists():
        return pd.read_parquet(p)
    parts = [pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float) for f in _files(sym) if f.exists()]
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[(df.high >= df.low) & (df.index <= END)]
    df.to_parquet(p)
    return df

@lru_cache(maxsize=2)
def m1_arrays(sym: str):
    df = load_m1(sym)
    t = df.index.as_unit("ns").asi8.astype(np.int64)
    return dict(t=t, o=df.open.to_numpy(), h=df.high.to_numpy(), l=df.low.to_numpy(), c=df.close.to_numpy(),
                index=df.index)

def _wilder_atr(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.empty_like(tr); out[:] = np.nan
    if len(tr) < n: return out
    out[n - 1] = tr[:n].mean()
    a = 1.0 / n
    for i in range(n, len(tr)):
        out[i] = out[i - 1] * (1 - a) + tr[i] * a
    out[:n - 1] = out[n - 1]
    return out

def tf_bars(sym: str, tf: str) -> pd.DataFrame:
    """Bars labelled by OPEN time (UTC); tclose = close time. D1 = NY 17:00 roll (crypto UTC)."""
    df = load_m1(sym)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if tf == "D1":
        if GROUP[sym] == "CRYPTO":
            b = df.resample("1D").agg(agg).dropna(); dur = pd.Timedelta(days=1)
        else:
            x = df.tz_convert("America/New_York").copy(); x.index = x.index + pd.Timedelta(hours=7)
            b = x.resample("1D").agg(agg).dropna(); b = b[b.index.dayofweek < 5]
            b.index = (b.index - pd.Timedelta(hours=7)).tz_convert("UTC"); dur = pd.Timedelta(days=1)
            # NY-roll day: true close = open + 24h (DST-safe enough at minute resolution for causality we use next open)
    else:
        rule = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}[tf]
        b = df.resample(rule, label="left", closed="left").agg(agg).dropna(); dur = pd.Timedelta(rule)
    b = b.copy()
    b["atr"] = _wilder_atr(b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy())
    b["ema20"] = b.close.ewm(span=20, adjust=False).mean()
    b["ema50"] = b.close.ewm(span=50, adjust=False).mean()
    b["tclose"] = b.index + dur
    return b

def asof_idx(tclose: np.ndarray, times_ns: np.ndarray) -> np.ndarray:
    """index of last bar with close <= t (strictly causal)."""
    return np.searchsorted(tclose, times_ns, side="right") - 1

def d1_trend(d1: pd.DataFrame, times_ns: np.ndarray, ema: str) -> np.ndarray:
    tc = d1["tclose"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    i = asof_idx(tc, times_ns)
    c = d1.close.to_numpy(); e = d1[ema].to_numpy()
    ok = i >= 50
    out = np.zeros(len(times_ns), np.int8)
    ii = np.clip(i, 0, len(c) - 1)
    out[ok] = np.where(c[ii][ok] > e[ii][ok], 1, -1)
    return out

# ------------------------------------------------------------------------------------------ OBX zones
def pivots(h, l, n):
    """strict fractal pivots (engine find_pivots): arrays is_ph, is_pl (pivot at i, confirmed at i+n)."""
    N = len(h); ph = np.zeros(N, bool); pl = np.zeros(N, bool)
    for i in range(n, N - n):
        wh = h[i - n:i + n + 1]; wl = l[i - n:i + n + 1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1: ph[i] = True
        if l[i] == wl.min() and (wl == l[i]).sum() == 1: pl[i] = True
    return ph, pl

def detect_obx(b: pd.DataFrame, n: int, sym: str, tf: str) -> pd.DataFrame:
    o = b.open.to_numpy(); h = b.high.to_numpy(); l = b.low.to_numpy(); c = b.close.to_numpy()
    atr = b.atr.to_numpy(); N = len(b)
    tclose = b["tclose"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    is_ph, is_pl = pivots(h, l, n)
    ph_list, pl_list = [], []          # confirmed pivots (idx, price)
    used_ph, used_pl = -1, -1
    rows = []
    for j in range(2 * n + 2, N):
        p = j - n
        if p >= n:
            if is_ph[p]: ph_list.append((p, h[p]))
            if is_pl[p]: pl_list.append((p, l[p]))
        a = atr[j]
        if not (a > 0): continue
        for bull in (True, False):
            lst = ph_list if bull else pl_list
            if not lst: continue
            pi, P = lst[-1]
            if bull and not (c[j] > P and pi != used_ph): continue
            if (not bull) and not (c[j] < P and pi != used_pl): continue
            if bull: used_ph = pi
            else: used_pl = pi
            k = pi + int(np.argmin(l[pi:j + 1])) if bull else pi + int(np.argmax(h[pi:j + 1]))
            ob = -1
            for i in range(k, max(k - 11, -1), -1):
                if (bull and c[i] < o[i]) or ((not bull) and c[i] > o[i]):
                    ob = i; break
            if ob < 0: continue
            conf = max(j, ob + 2)
            if conf >= N: continue
            zlo, zhi = l[ob], h[ob]
            seg = slice(ob + 3, conf + 1)
            if ob + 3 <= conf and np.any((l[seg] <= zhi) & (h[seg] >= zlo)):
                continue
            # FVG in leg (middle candle in (ob, conf-1])
            fvg = False
            for i in range(ob + 1, conf):
                if bull and h[i - 1] < l[i + 1]: fvg = True; break
                if (not bull) and l[i - 1] > h[i + 1]: fvg = True; break
            s1 = (h[ob] < l[ob + 2]) if bull else (l[ob] > h[ob + 2])
            # s2 pivot trend before j (confirmed pivots, idx < j)
            hs_ = [q for q in ph_list if q[0] < j][-2:]; ls_ = [q for q in pl_list if q[0] < j][-2:]
            tr = 0
            if len(hs_) == 2 and len(ls_) == 2:
                if hs_[1][1] > hs_[0][1] and ls_[1][1] > ls_[0][1]: tr = 1
                elif hs_[1][1] < hs_[0][1] and ls_[1][1] < ls_[0][1]: tr = -1
            s2 = (tr == 1) if bull else (tr == -1)
            if bull:
                lo_, hi_ = l[k], h[k:conf + 1].max(); s3 = zhi <= lo_ + 0.5 * (hi_ - lo_)
                liq_pre = h[k:conf + 1].max()
            else:
                hi_, lo_ = h[k], l[k:conf + 1].min(); s3 = zlo >= hi_ - 0.5 * (hi_ - lo_)
                liq_pre = l[k:conf + 1].min()
            tol = max(0.1 * a, 0.0005 * abs((zlo + zhi) / 2))
            s4 = True
            if bull:
                for (pi2, pp) in pl_list:
                    if pi2 >= ob or pi2 < ob - 500: continue
                    if zlo - a <= pp <= zlo and not np.any(l[pi2 + 1:ob] <= pp + tol): s4 = False; break
            else:
                for (pi2, pp) in ph_list:
                    if pi2 >= ob or pi2 < ob - 500: continue
                    if zhi <= pp <= zhi + a and not np.any(h[pi2 + 1:ob] >= pp - tol): s4 = False; break
            rows.append(dict(sym=sym, tf=tf, side=1 if bull else -1, ob_i=ob, k=k, j=j, conf=conf,
                             t_conf=tclose[conf], zlo=zlo, zhi=zhi, atr=atr[conf], fvg=fvg,
                             s1=bool(s1), s2=bool(s2), s3=bool(s3), s4=bool(s4), liq_pre=liq_pre))
    z = pd.DataFrame(rows)
    if z.empty: return z
    z["score4"] = z[["s1", "s2", "s3", "s4"]].sum(axis=1)
    z["t_active"] = z["t_conf"] + DELAY_MIN * 60_000_000_000
    return z

# ------------------------------------------------------------------------------------------ simulator
@njit(cache=True)
def find_fill(t, o, h, l, c, start_i, side, etype, level, expiry_ns, hs):
    """Stage 1. Returns fill index, entry price, and running extreme (max high for longs / min low for shorts)
    over [start, fill) — used for the causal LIQ target."""
    n_tr = start_i.shape[0]; N = t.shape[0]
    f_out = np.full(n_tr, -1, np.int64); e_out = np.full(n_tr, np.nan); x_out = np.full(n_tr, np.nan)
    for j in range(n_tr):
        s = start_i[j]
        if s < 0 or s >= N: continue
        lng = side[j] > 0; L = level[j]; H = hs[j]
        if etype[j] == 0:
            f_out[j] = s; e_out[j] = o[s] + H if lng else o[s] - H   # slippage added in stage 2
            continue
        tmax = t[s] + expiry_ns[j]
        ext = -1e300 if lng else 1e300
        k = s
        while k < N and t[k] < tmax:
            if lng and l[k] <= L - H:
                f_out[j] = k; e_out[j] = min(L, o[k] + H); break
            if (not lng) and h[k] >= L + H:
                f_out[j] = k; e_out[j] = max(L, o[k] - H); break
            if lng: ext = max(ext, h[k])
            else: ext = min(ext, l[k])
            k += 1
        x_out[j] = ext
    return f_out, e_out, x_out

@njit(cache=True)
def run_exit(t, o, h, l, c, f_i, side, etype, epx0, level, sl, tp, hold_ns, hs, slip, mgmt, trail_lo, trail_hi):
    """Stage 2 from fill bar f. tp = absolute TP price (nan = none). mgmt: 0 none, 1 BE@+1R, 2 50% partial@+1R + BE,
    3 structure trail after +1R (trail_lo/hi = extreme of last 3 closed bars of the trail TF, per M1 bar).
    Returns exit idx, r_gross (before commission), why (1 tp 2 sl 3 time 4 eod 5 invalid), risk, entry px."""
    n_tr = f_i.shape[0]; N = t.shape[0]
    x_out = np.full(n_tr, -1, np.int64); r_out = np.full(n_tr, np.nan); w_out = np.zeros(n_tr, np.int8)
    rk_out = np.full(n_tr, np.nan); ep_out = np.full(n_tr, np.nan)
    for j in range(n_tr):
        f = f_i[j]
        if f < 0: continue
        lng = side[j] > 0; H = hs[j]; sp = slip[j]; S = sl[j]; T = tp[j]
        if etype[j] == 0:
            epx = epx0[j] + sp if lng else epx0[j] - sp
            risk = (epx - S) if lng else (S - epx); ref = epx
        else:
            epx = epx0[j]; risk = (level[j] - S) if lng else (S - level[j]); ref = level[j]
        if not (risk > 0):
            w_out[j] = 5; continue
        P1 = ref + risk if lng else ref - risk
        rem = 1.0; pnl = 0.0; armed = False; pdone = False
        tend = t[f] + hold_ns[j]
        k = f; done = False
        while k < N and t[k] < tend:
            if armed and mgmt == 3:
                if lng:
                    if trail_lo[k] > S: S = trail_lo[k]
                else:
                    if trail_hi[k] < S: S = trail_hi[k]
            if lng:
                if l[k] <= S + H:
                    xp = min(S, o[k] - H) - sp if k > f else S - sp
                    pnl += rem * (xp - epx); x_out[j] = k; w_out[j] = 2; done = True; break
                if mgmt == 2 and not pdone:
                    hit1 = (c[k] >= P1 + H) if k == f else (h[k] >= P1 + H)
                    if hit1:
                        xp1 = P1 if k == f else max(P1, o[k] - H)
                        pnl += 0.5 * (xp1 - epx); rem = 0.5; pdone = True
                if T == T:
                    tp_hit = (c[k] >= T + H) if k == f else (h[k] >= T + H)
                    if tp_hit:
                        xp = T if k == f else max(T, o[k] - H)
                        pnl += rem * (xp - epx); x_out[j] = k; w_out[j] = 1; done = True; break
                if (not armed) and mgmt > 0 and h[k] >= P1:
                    armed = True
                    if mgmt == 1 or mgmt == 2:
                        if ref > S: S = ref
            else:
                if h[k] >= S - H:
                    xp = max(S, o[k] + H) + sp if k > f else S + sp
                    pnl += rem * (epx - xp); x_out[j] = k; w_out[j] = 2; done = True; break
                if mgmt == 2 and not pdone:
                    hit1 = (c[k] <= P1 - H) if k == f else (l[k] <= P1 - H)
                    if hit1:
                        xp1 = P1 if k == f else min(P1, o[k] + H)
                        pnl += 0.5 * (epx - xp1); rem = 0.5; pdone = True
                if T == T:
                    tp_hit = (c[k] <= T - H) if k == f else (l[k] <= T - H)
                    if tp_hit:
                        xp = T if k == f else min(T, o[k] + H)
                        pnl += rem * (epx - xp); x_out[j] = k; w_out[j] = 1; done = True; break
                if (not armed) and mgmt > 0 and l[k] <= P1:
                    armed = True
                    if mgmt == 1 or mgmt == 2:
                        if ref < S: S = ref
            k += 1
        if not done:
            kl = k - 1
            if kl < f: kl = f
            w_out[j] = 4 if k >= N else 3
            x_out[j] = kl
            xp = c[kl] - H - sp if lng else c[kl] + H + sp
            pnl += rem * ((xp - epx) if lng else (epx - xp))
        r_out[j] = pnl / risk; rk_out[j] = risk; ep_out[j] = epx
    return x_out, r_out, w_out, rk_out, ep_out

def trail_arrays(sym: str, b: pd.DataFrame, nb: int = 3):
    """per M1 bar: lowest low / highest high of the last nb TF bars CLOSED at or before the M1 bar open."""
    A = m1_arrays(sym)
    lo3 = b.low.rolling(nb, min_periods=1).min().to_numpy(); hi3 = b.high.rolling(nb, min_periods=1).max().to_numpy()
    tc = b["tclose"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    i = asof_idx(tc, A["t"])
    ok = i >= 0; ii = np.clip(i, 0, len(b) - 1)
    tl = np.where(ok, lo3[ii], -np.inf); th = np.where(ok, hi3[ii], np.inf)
    return tl.astype(float), th.astype(float)

def swap_r(sym, side, price, days, risk, mult=1.0):
    g = GROUP[sym]; lr, sr = SWAP[g]
    rate = np.where(np.asarray(side) > 0, lr, sr)
    return mult * np.asarray(price) * rate * np.asarray(days) / 365.0 / np.asarray(risk)

# ------------------------------------------------------------------------------------------- metrics
def weeks(a, b):
    return (b - a).total_seconds() / (7 * 86400)

def metrics(r: np.ndarray, span_weeks: float) -> dict:
    r = np.asarray(r, float); n = len(r)
    if n == 0:
        return dict(n=0, per_wk=0.0, wr=np.nan, avg=np.nan, lo=np.nan, hi=np.nan, t=np.nan, pf=np.nan, sum=0.0,
                    maxdd=0.0, streak=0)
    m = r.mean(); sd = r.std(ddof=1) if n > 1 else np.nan; se = sd / math.sqrt(n) if n > 1 else np.nan
    eq = np.cumsum(r); dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq))
    g = r[r > 0].sum(); ls = -r[r < 0].sum()
    st = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0; st = max(st, cur)
    return dict(n=n, per_wk=n / span_weeks if span_weeks else np.nan, wr=float((r > 0).mean()), avg=float(m),
                lo=float(m - 1.96 * se) if n > 1 else np.nan, hi=float(m + 1.96 * se) if n > 1 else np.nan,
                t=float(m / se) if n > 1 and se > 0 else np.nan, pf=float(g / ls) if ls > 0 else np.inf,
                sum=float(r.sum()), maxdd=dd, streak=int(st))
