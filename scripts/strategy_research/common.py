"""Shared data access, cost model, M1 trade simulator and metrics for the strategy research.

Conventions
-----------
* All raw data = M1 bars, UTC index (HistData forex/metals/indices/WTI, Binance spot crypto).
* Prices are treated as MID. Spread is modelled explicitly per leg:
    buy limit L fills only if low <= L - half_spread (ask trades through L); fill price L
    buy stop  L fills if high >= L - half_spread; fill price L + slip (or worse open on a gap)
    market buy at bar open: open + half_spread + slip
    long SL S (sell stop) triggers if low <= S + half_spread; fill S - slip (or worse open on a gap)
    long TP T (sell limit) fills only if high >= T + half_spread; fill T
    time exit (market): close -/+ half_spread -/+ slip
  shorts symmetric; commission (round trip, price units) subtracted from PnL.
* Same-bar ambiguity: on any bar where SL and TP are both reachable -> SL. On the fill bar, TP only counts
  if the bar CLOSES beyond TP (conservative), SL counts if touched.
* R unit = planned risk |entry level - SL| for limit/stop orders, |fill - SL| for market orders.
"""
from __future__ import annotations
import math
from functools import lru_cache
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit

ROOT = Path(__file__).resolve().parents[2]
M1_DIR = ROOT / "data/cache/strategy_research/m1"
OUT = ROOT / "data/backtest/strategy_research"
OUT.mkdir(parents=True, exist_ok=True)

DATA_START = pd.Timestamp("2023-01-02", tz="UTC")
SPLIT = pd.Timestamp("2025-07-01", tz="UTC")      # train < SPLIT <= test (pre-registered)
DATA_END = pd.Timestamp("2026-09-30 21:00", tz="UTC")

GROUP = {"XAUUSD": "METALS", "XAGUSD": "METALS",
         "EURUSD": "FOREX", "GBPUSD": "FOREX", "USDJPY": "FOREX", "USDCAD": "FOREX", "AUDUSD": "FOREX",
         "USDCHF": "FOREX", "EURJPY": "FOREX", "GBPJPY": "FOREX", "EURGBP": "FOREX",
         "US500": "INDICES", "NAS100": "INDICES", "DAX": "INDICES",
         "BTC": "CRYPTO", "ETH": "CRYPTO", "SOL": "CRYPTO"}
ALL = list(GROUP)

# Cost model (price units). spread = full typical spread during London/NY on a good ECN/raw account,
# comm = round-trip commission, slip = extra slippage per stop/market leg (manual execution).
PIP = {"EURUSD": 1e-4, "GBPUSD": 1e-4, "USDCAD": 1e-4, "AUDUSD": 1e-4, "USDCHF": 1e-4, "EURGBP": 1e-4,
       "USDJPY": 1e-2, "EURJPY": 1e-2, "GBPJPY": 1e-2}
_FX_SPREAD_PIPS = {"EURUSD": 0.2, "GBPUSD": 0.4, "USDJPY": 0.3, "USDCAD": 0.5, "AUDUSD": 0.3,
                   "USDCHF": 0.5, "EURJPY": 0.6, "GBPJPY": 1.0, "EURGBP": 0.5}

def costs(sym: str, price: float) -> tuple[float, float, float]:
    """(spread, commission_round_trip, slip_per_stop_or_market_leg) in price units."""
    if sym in _FX_SPREAD_PIPS:
        p = PIP[sym]
        return _FX_SPREAD_PIPS[sym] * p, 0.6 * p, 0.2 * p    # 0.6 pip ~ $6/lot RT commission
    if sym == "XAUUSD":
        return 0.25, 0.07, 0.10
    if sym == "XAGUSD":
        return 0.025, 0.004, 0.01
    if sym == "US500":
        return 0.5, 0.0, 0.25
    if sym == "NAS100":
        return 1.5, 0.0, 1.0
    if sym == "DAX":
        return 1.5, 0.0, 1.0
    if sym == "WTI":
        return 0.03, 0.0, 0.02
    if sym in ("BTC", "ETH", "SOL"):
        # perp/spot: ~0.01% spread, 0.05% round-trip commission (maker/taker mix), 0.02% slippage per leg
        return 1e-4 * price, 5e-4 * price, 2e-4 * price
    raise KeyError(sym)

# ---------------------------------------------------------------------------------------------- data
@lru_cache(maxsize=None)
def load_m1(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(M1_DIR / f"{sym}_M1.parquet")[["open", "high", "low", "close"]].astype(float)
    df = df[(df.index >= DATA_START - pd.Timedelta(days=40)) & (df.index <= DATA_END)]
    df = df[(df.high >= df.low)]
    return df

@lru_cache(maxsize=None)
def arrays(sym: str):
    df = load_m1(sym)
    t = df.index.as_unit("ns").asi8.astype(np.int64)  # ns (pandas 3 may default to us)
    loc = df.index.tz_convert("Europe/Paris")
    mod = (loc.hour * 60 + loc.minute).to_numpy(np.int32)          # Paris minute of day
    day = (loc.normalize().as_unit("ns").asi8 // 86_400_000_000_000).astype(np.int64)  # Paris calendar day id
    return dict(t=t, o=df.open.to_numpy(), h=df.high.to_numpy(), l=df.low.to_numpy(), c=df.close.to_numpy(),
                mod=mod, day=day, dow=loc.dayofweek.to_numpy(np.int8), index=df.index)

def resample(sym: str, rule: str, tz: str = "UTC", offset: str | None = None) -> pd.DataFrame:
    """OHLC bars labelled by bar OPEN time (UTC index). Bars only from existing minutes."""
    df = load_m1(sym)
    x = df.tz_convert(tz) if tz != "UTC" else df
    r = x.resample(rule, label="left", closed="left", offset=offset).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    r.index = r.index.tz_convert("UTC")
    return r

def daily(sym: str) -> pd.DataFrame:
    """D1 bars: crypto UTC days; others NY 17:00 roll (FX convention). Index = day OPEN time (UTC)."""
    if GROUP[sym] == "CRYPTO":
        return resample(sym, "1D")
    df = load_m1(sym).tz_convert("America/New_York")
    shifted = df.copy(); shifted.index = shifted.index + pd.Timedelta(hours=7)  # 17:00 NY -> 00:00
    r = shifted.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    r = r[r.index.dayofweek < 5]
    r.index = (r.index - pd.Timedelta(hours=7)).tz_convert("UTC")
    return r

# ----------------------------------------------------------------------------------------- simulator
@njit(cache=True)
def _sim(t, o, h, l, c, start_i, side, etype, level, sl, tp_r, tp_abs, expiry_ns, hold_ns, hs, slip):
    n_tr = start_i.shape[0]; N = t.shape[0]
    out_fill = np.full(n_tr, -1, np.int64); out_exit = np.full(n_tr, -1, np.int64)
    out_epx = np.full(n_tr, np.nan); out_xpx = np.full(n_tr, np.nan)
    out_risk = np.full(n_tr, np.nan); out_why = np.zeros(n_tr, np.int8)  # 1 tp 2 sl 3 time 4 eod 5 invalid
    for j in range(n_tr):
        s = start_i[j]
        if s < 0 or s >= N:
            continue
        lng = side[j] > 0
        L = level[j]; S = sl[j]; H = hs[j]; sp = slip[j]
        # ---- fill
        f = -1; epx = np.nan
        if etype[j] == 0:  # market at open of bar s
            f = s
            epx = o[s] + H + sp if lng else o[s] - H - sp
        else:
            tmax = t[s] + expiry_ns[j]
            k = s
            while k < N and t[k] < tmax:
                if etype[j] == 1:  # limit
                    if lng and l[k] <= L - H:
                        f = k; epx = min(L, o[k] + H); break
                    if (not lng) and h[k] >= L + H:
                        f = k; epx = max(L, o[k] - H); break
                else:              # stop
                    if lng and h[k] >= L - H:
                        f = k; epx = max(L, o[k] + H) + sp; break
                    if (not lng) and l[k] <= L + H:
                        f = k; epx = min(L, o[k] - H) - sp; break
                k += 1
        if f < 0:
            continue
        if etype[j] == 0:
            risk = (epx - S) if lng else (S - epx)
            ref = epx
        else:
            risk = (L - S) if lng else (S - L)
            ref = L
        if risk <= 0:
            out_why[j] = 5; out_fill[j] = f; continue
        if tp_r[j] > 0:
            T = ref + tp_r[j] * risk if lng else ref - tp_r[j] * risk
        else:
            T = tp_abs[j]
        out_fill[j] = f; out_epx[j] = epx; out_risk[j] = risk
        tend = t[f] + hold_ns[j]
        k = f; done = False
        while k < N and t[k] < tend:
            if lng:
                if l[k] <= S + H:
                    out_exit[j] = k; out_xpx[j] = min(S, o[k] - H) - sp if k > f else S - sp; out_why[j] = 2; done = True; break
                tp_hit = (c[k] >= T + H) if k == f else (h[k] >= T + H)
                if tp_hit:
                    out_exit[j] = k; out_xpx[j] = T if k == f else max(T, o[k] - H); out_why[j] = 1; done = True; break
            else:
                if h[k] >= S - H:
                    out_exit[j] = k; out_xpx[j] = max(S, o[k] + H) + sp if k > f else S + sp; out_why[j] = 2; done = True; break
                tp_hit = (c[k] <= T - H) if k == f else (l[k] <= T - H)
                if tp_hit:
                    out_exit[j] = k; out_xpx[j] = T if k == f else min(T, o[k] + H); out_why[j] = 1; done = True; break
            k += 1
        if not done:
            kl = k - 1
            if kl < f:
                kl = f
            if k >= N:
                out_why[j] = 4
            else:
                out_why[j] = 3
            out_exit[j] = kl
            out_xpx[j] = c[kl] - H - sp if lng else c[kl] + H + sp
    return out_fill, out_exit, out_epx, out_xpx, out_risk, out_why

WHY = {0: "nofill", 1: "tp", 2: "sl", 3: "time", 4: "eod", 5: "invalid"}

def simulate(req: pd.DataFrame, cost_mult: float = 1.0) -> pd.DataFrame:
    """req columns: sym, t_active (UTC Timestamp: order live from this minute), side (+1/-1),
    etype ('market'|'limit'|'stop'), level, sl, tp_r (R multiple, or 0), tp_abs, expiry_min, hold_min.
    Extra columns are passed through. Returns filled trades with r_gross / r_net."""
    if req.empty:
        return req.assign(r_net=[])
    outs = []
    et_map = {"market": 0, "limit": 1, "stop": 2}
    for sym, g in req.groupby("sym", sort=False):
        A = arrays(sym)
        g = g.copy()
        ta = pd.DatetimeIndex(g["t_active"]).tz_convert("UTC").as_unit("ns").asi8
        si = np.searchsorted(A["t"], ta, side="left").astype(np.int64)
        px = g["level"].to_numpy(float)
        sp, cm, sl_ = zip(*[costs(sym, p) for p in px])
        sp = np.array(sp) * cost_mult; cm = np.array(cm) * cost_mult; sl_ = np.array(sl_) * cost_mult
        res = _sim(A["t"], A["o"], A["h"], A["l"], A["c"], si, g["side"].to_numpy(np.int64),
                   g["etype"].map(et_map).to_numpy(np.int64), px, g["sl"].to_numpy(float),
                   g["tp_r"].fillna(0).to_numpy(float), g.get("tp_abs", pd.Series(np.nan, index=g.index)).to_numpy(float),
                   (g["expiry_min"].to_numpy(float) * 6e10).astype(np.int64), (g["hold_min"].to_numpy(float) * 6e10).astype(np.int64),
                   sp / 2.0, sl_)
        f, x, epx, xpx, risk, why = res
        g["fill_i"] = f; g["why"] = [WHY[int(w)] for w in why]
        g["entry_px"] = epx; g["exit_px"] = xpx; g["risk"] = risk
        idx = A["index"]
        g["t_fill"] = [idx[i] if i >= 0 else pd.NaT for i in f]
        g["t_exit"] = [idx[i] if i >= 0 else pd.NaT for i in x]
        g["comm"] = cm; g["cost_mult"] = cost_mult
        outs.append(g)
    r = pd.concat(outs)
    r = r[r["why"].isin(["tp", "sl", "time", "eod"])].copy()
    sgn = r["side"].astype(float)
    r["r_gross"] = sgn * (r["exit_px"] - r["entry_px"]) / r["risk"]
    r["r_net"] = r["r_gross"] - r["comm"] / r["risk"]
    r["group"] = r["sym"].map(GROUP)
    r = r.sort_values("t_fill").reset_index(drop=True)
    return r

# ------------------------------------------------------------------------------------------- metrics
def weekdays_between(a: pd.Timestamp, b: pd.Timestamp) -> float:
    return float(np.busday_count(a.date(), b.date()))

def metrics(tr: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp], col: str = "r_net") -> dict:
    wd = weekdays_between(*period)
    n = len(tr)
    if n == 0:
        return dict(n=0, per_wd=0.0, wr=np.nan, avg=np.nan, lo=np.nan, hi=np.nan, t=np.nan, pf=np.nan,
                    sum=0.0, maxdd=0.0, streak=0)
    r = tr.sort_values("t_fill")[col].to_numpy(float)
    m = r.mean(); sd = r.std(ddof=1) if n > 1 else np.nan
    se = sd / math.sqrt(n) if n > 1 else np.nan
    eq = np.cumsum(r); dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq)) if n else 0
    gains = r[r > 0].sum(); loss = -r[r < 0].sum()
    streak = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        streak = max(streak, cur)
    return dict(n=n, per_wd=n / wd if wd else np.nan, wr=float((r > 0).mean()), avg=float(m),
                lo=float(m - 1.96 * se) if n > 1 else np.nan, hi=float(m + 1.96 * se) if n > 1 else np.nan,
                t=float(m / se) if n > 1 and se > 0 else np.nan, pf=float(gains / loss) if loss > 0 else np.inf,
                sum=float(r.sum()), maxdd=dd, streak=int(streak))

def split(tr: pd.DataFrame):
    t = pd.DatetimeIndex(tr["t_fill"])
    return tr[t < SPLIT], tr[t >= SPLIT]

TRAIN = (DATA_START, SPLIT)
TEST = (SPLIT, DATA_END)

# ------------------------------------------------------------------------------------------ features
@lru_cache(maxsize=None)
def local(sym: str, tz: str) -> pd.DataFrame:
    """M1 bars with local minute-of-day and local date (for session windows)."""
    df = load_m1(sym).copy()
    loc = df.index.tz_convert(tz)
    df["mod"] = (loc.hour * 60 + loc.minute).astype(np.int32)
    df["date"] = loc.tz_localize(None).normalize()
    df["dow"] = loc.dayofweek
    return df

def _wilder_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()

@lru_cache(maxsize=None)
def bars(sym: str, tf: str) -> pd.DataFrame:
    """Bars with indicators; 'tclose' = bar close time (UTC) for causal lookup."""
    if tf == "D1":
        b = daily(sym); dur = pd.Timedelta(days=1)
    else:
        rule = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}[tf]
        b = resample(sym, rule); dur = pd.Timedelta(rule)
    b = b.copy()
    b["atr"] = _wilder_atr(b, 14)
    b["ema20"] = b.close.ewm(span=20, adjust=False).mean()
    b["ema50"] = b.close.ewm(span=50, adjust=False).mean()
    b["tclose"] = b.index + dur
    return b

def asof(sym: str, tf: str, times, col: str) -> np.ndarray:
    """Value of `col` on the last bar of `tf` whose close time <= t (strictly causal)."""
    b = bars(sym, tf)
    tc = b["tclose"].to_numpy(dtype="datetime64[ns]")
    tt = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None).to_numpy(dtype="datetime64[ns]")
    i = np.searchsorted(tc, tt, side="right") - 1
    v = b[col].to_numpy(float)
    out = np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
    return out

def trend(sym: str, tf: str, times, ema: str = "ema20") -> np.ndarray:
    """+1 if last closed bar close > EMA, -1 otherwise (NaN-safe -> 0)."""
    c = asof(sym, tf, times, "close"); e = asof(sym, tf, times, ema)
    return np.where(np.isnan(c) | np.isnan(e), 0, np.where(c > e, 1, -1))
