"""OB 5★ on XAUUSD only, multi-timeframe (M5 M15 M30 H1 H4 D1 W) — pre-registered in PREREG_OB_XAU.md.

Research only. Reuses common.py (cost model, numba M1 simulator core `_sim`) and the repo engine
backend/app/engine/detect.py (unchanged). XAU M1 = HistData (= Dukascopy BID) 2019-01 -> 2026-09-30;
2019-2022 is used for detection warm-up and as a supplementary PRE-SAMPLE hold-out (2020-2022), never for selection.

Usage:
  .venv/bin/python scripts/strategy_research/ob_xau_multitf.py detect [TF ...]   # causal walk-forward detection
  .venv/bin/python scripts/strategy_research/ob_xau_multitf.py grid               # full grid (1x, 0x costs)
  .venv/bin/python scripts/strategy_research/ob_xau_multitf.py select             # TRAIN ranking -> frozen -> TEST + stress
  .venv/bin/python scripts/strategy_research/ob_xau_multitf.py baseline           # random-entry baseline
"""
from __future__ import annotations
import itertools, json, math, pickle, sys, time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
sys.path.insert(0, str(HERE))
from common import ROOT, SPLIT, costs, _sim, _wilder_atr  # noqa: E402

SYM = "XAUUSD"
CACHE = ROOT / "data/cache/strategy_research/ob_xau"
OUTX = ROOT / "data/backtest/strategy_research/ob_xau"
CACHE.mkdir(parents=True, exist_ok=True); OUTX.mkdir(parents=True, exist_ok=True)

PRE_START = pd.Timestamp("2020-01-01", tz="UTC")     # supplementary pre-sample hold-out
MAIN_START = pd.Timestamp("2023-01-02", tz="UTC")    # TRAIN start (framework data start)
END = pd.Timestamp("2026-09-30 21:00", tz="UTC")
PERIODS = {"pre": (PRE_START, MAIN_START), "train": (MAIN_START, SPLIT), "test": (SPLIT, END)}

TFS = ["M5", "M15", "M30", "H1", "H4", "D1", "W"]
HTF = {"H4", "D1", "W"}                               # engine: ★5 pending until touch (session at touch)
ENG_TF = {"M5": "M5", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4", "D1": "D", "W": "W"}
PIVOT = {"M5": 3, "M15": 3, "M30": 3, "H1": 3, "H4": 3, "D1": 2, "W": 2}
LOOKBACK = {"M5": 300, "M15": 300, "M30": 300, "H1": 500, "H4": 500, "D1": 400, "W": 260}
WARM = {"M5": 300, "M15": 300, "M30": 300, "H1": 500, "H4": 500, "D1": 150, "W": 60}
RULE = {"M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}
DELAY = 3
EXPIRY_MIN = {"M5": 120, "M15": 360, "M30": 720, "H1": 1440, "H4": 4 * 1440, "D1": 28 * 1440, "W": 84 * 1440}
SHORT_HOLDS = [60, 120, 180]
LONG_HOLDS = {"H4": [1440, 2880], "D1": [3 * 1440, 5 * 1440], "W": [14 * 1440, 28 * 1440]}
SWAP_LONG, SWAP_SHORT = 0.00020, 0.00010             # fraction of price per 17:00 NY rollover (Wed x3), both charged

# ------------------------------------------------------------------------------------------------ data
@lru_cache(maxsize=None)
def m1() -> pd.DataFrame:
    a = pd.read_parquet(ROOT / "data/cache/strategy_research/m1/XAUUSD_M1_2019_2022.parquet")
    b = pd.read_parquet(ROOT / "data/cache/strategy_research/m1/XAUUSD_M1.parquet")
    df = pd.concat([a, b])[["open", "high", "low", "close"]].astype(float).sort_index()
    df = df[~df.index.duplicated()]
    df = df[(df.index <= END) & (df.high >= df.low)]
    return df

@lru_cache(maxsize=None)
def arrays():
    df = m1()
    t = df.index.as_unit("ns").asi8.astype(np.int64)
    loc = df.index.tz_convert("Europe/Paris")
    mod = (loc.hour * 60 + loc.minute).to_numpy(np.int32)
    ny = df.index.tz_convert("America/New_York")
    # rollover id: NY trading day (17:00 NY roll) -> number of rollovers crossed = diff of ids
    rid = ((ny.tz_localize(None) + pd.Timedelta(hours=7)).normalize().as_unit("ns").asi8 // 86_400_000_000_000).astype(np.int64)
    return dict(t=t, o=df.open.to_numpy(), h=df.high.to_numpy(), l=df.low.to_numpy(), c=df.close.to_numpy(),
                mod=mod, rid=rid, index=df.index)

def _daily(df: pd.DataFrame) -> pd.DataFrame:
    x = df.tz_convert("America/New_York").copy(); x.index = x.index + pd.Timedelta(hours=7)
    r = x.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    r = r[r.index.dayofweek < 5]
    r.index = (r.index - pd.Timedelta(hours=7)).tz_convert("UTC")
    return r

@lru_cache(maxsize=None)
def bars(tf: str) -> pd.DataFrame:
    """Bars labelled by OPEN time (UTC) + 'tclose' + ATR14 (Wilder) + EMA50."""
    df = m1()
    if tf in RULE:
        b = df.resample(RULE[tf], label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        b["tclose"] = b.index + pd.Timedelta(RULE[tf])
    elif tf == "D1":
        b = _daily(df); b["tclose"] = b.index + pd.Timedelta(days=1)
    elif tf == "W":
        d = _daily(df)
        nyday = (d.index.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)).normalize()
        wk = nyday - pd.to_timedelta(nyday.dayofweek, unit="D")
        g = d.assign(wk=wk.values, t0=d.index).groupby("wk")
        b = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last(),
                          "t0": g.t0.first(), "tclose": g.t0.last() + pd.Timedelta(days=1)})
        b.index = pd.DatetimeIndex(b.pop("t0")); b.index.name = None
    b = b.copy()
    b["atr"] = _wilder_atr(b, 14)
    b["ema50"] = b.close.ewm(span=50, adjust=False).mean()
    return b

def asof(tf: str, times, col: str) -> np.ndarray:
    b = bars(tf)
    tc = pd.DatetimeIndex(b["tclose"]).tz_convert("UTC").tz_localize(None).to_numpy("datetime64[ns]")
    tt = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None).to_numpy("datetime64[ns]")
    i = np.searchsorted(tc, tt, side="right") - 1
    v = b[col].to_numpy(float)
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)

def trend_at(tf: str, times) -> np.ndarray:
    c = asof(tf, times, "close"); e = asof(tf, times, "ema50")
    return np.where(np.isnan(c) | np.isnan(e), 0, np.where(c > e, 1, -1))

# ------------------------------------------------------------------------------------------- detection
_HB: dict = {}
def _detect_chunk(args):
    tf, a, b = args[:3]
    relaxed = len(args) > 3 and args[3] == "x"
    from app.engine.detect import detect_zones
    from app.engine.params import EngineParams
    if tf not in _HB:
        _HB.clear(); _HB[tf] = pd.read_parquet(CACHE / f"bars_{tf}.parquet")
    h = _HB[tf]
    lb = LOOKBACK[tf]
    p = EngineParams(pivot_n=PIVOT[tf], lookback=lb, entry_mode="mid")
    min_s = 0 if relaxed else (2 if tf in HTF else 3)
    seen, out = set(), []
    for j in range(a, min(b, len(h))):
        sub = h.iloc[max(0, j - lb - 2): j + 1]
        for z in detect_zones(sub, symbol=SYM, tf=ENG_TF[tf], params=p, min_score=min_s, require_fresh=True,
                              require_fvg=not relaxed):
            for lvl in range(min_s, 6):
                if z.score < lvl:
                    break
                key = (z.direction, z.ts_ob, lvl)
                if key in seen:
                    continue
                seen.add(key)
                out.append(dict(tf=tf, direction=z.direction, ts_ob=z.ts_ob, ts_bos=z.ts_bos, level=lvl, score=z.score,
                                low=z.low, high=z.high, open=z.open, atr=z.atr, entry_eng=z.entry, sl_eng=z.sl,
                                det_time=h.index[j], s1=z.star1_fvg, s2=z.star2_trend, s3=z.star3_fib,
                                s4=z.star4_liquidity, s5=z.star5_session))
    return tf, out

def detect(tfs, mode="main"):
    tasks = []
    for tf in tfs:
        b = bars(tf)[["open", "high", "low", "close"]]
        b.to_parquet(CACHE / f"bars_{tf}.parquet")
        chunk = 8000
        for a in range(WARM[tf], len(b), chunk):
            tasks.append((tf, a, a + chunk, mode))
    print("tasks", len(tasks), flush=True)
    res = {tf: [] for tf in tfs}; t0 = time.time(); done = 0
    with ProcessPoolExecutor(7) as ex:
        for tf, z in ex.map(_detect_chunk, tasks, chunksize=1):
            res[tf].extend(z); done += 1
            if done % 10 == 0:
                print(f"{done}/{len(tasks)} {time.time()-t0:.0f}s", flush=True)
    for tf in tfs:
        best = {}
        for z in res[tf]:
            k = (z["direction"], z["ts_ob"], z["level"])
            if k not in best or z["det_time"] < best[k]["det_time"]:
                best[k] = z
        zs = pd.DataFrame(sorted(best.values(), key=lambda z: z["det_time"]))
        zs.to_pickle(CACHE / (f"zones_{tf}.pkl" if mode == "main" else f"zones_{tf}_x.pkl"))
        print("saved", tf, len(zs), zs.groupby("level").size().to_dict() if len(zs) else {}, f"{time.time()-t0:.0f}s", flush=True)

# -------------------------------------------------------------------------------------------- helpers
from numba import njit  # noqa: E402

ENG_WIN = ((480, 690), (870, 1050))      # engine ★5 windows, Paris (London 08:00-11:30, NY 14:30-17:30)
LONNY = ((480, 720), (870, 1080))        # session filter on fills, Paris (08:00-12:00, 14:30-18:00)

def in_win(mod, wins) -> np.ndarray:
    mod = np.asarray(mod)
    m = np.zeros(mod.shape, bool)
    for a, b in wins:
        m |= (mod >= a) & (mod < b)
    return m

@njit(cache=True)
def _first_touch(t, h, l, start_i, expiry_ns, side, prox):
    n = start_i.shape[0]; N = t.shape[0]
    out = np.full(n, -1, np.int64)
    for j in range(n):
        s = start_i[j]
        if s < 0 or s >= N:
            continue
        tmax = t[s] + expiry_ns[j]
        k = s
        while k < N and t[k] < tmax:
            if side[j] > 0 and l[k] <= prox[j]:
                out[j] = k; break
            if side[j] < 0 and h[k] >= prox[j]:
                out[j] = k; break
            k += 1
    return out

@lru_cache(maxsize=None)
def _swap_cum():
    A = arrays()
    lo, hi = int(A["rid"].min()) - 2, int(A["rid"].max()) + 2
    ids = np.arange(lo, hi + 1)
    dow = (ids + 3) % 7                                  # 1970-01-01 = Thursday; Mon=0
    w = np.where(dow >= 5, 0, np.where(dow == 3, 3, 1))  # trading day id reached after a rollover; Thu = Wed-night x3
    return lo, np.cumsum(w)

def nights(fill_i, exit_i) -> np.ndarray:
    A = arrays(); lo, cum = _swap_cum()
    return cum[A["rid"][exit_i] - lo] - cum[A["rid"][fill_i] - lo]

@lru_cache(maxsize=None)
def zones(tf: str, kind: str = "main") -> pd.DataFrame:
    """One row per zone (direction, ts_ob): geometry + first time each score level was reached."""
    z = pd.read_pickle(CACHE / (f"zones_{tf}.pkl" if kind == "main" else f"zones_{tf}_x.pkl"))
    g = z.sort_values("level").groupby(["direction", "ts_ob"], sort=False)
    base = g.first().reset_index()
    piv = z.pivot_table(index=["direction", "ts_ob"], columns="level", values="det_time", aggfunc="min")
    piv.columns = [f"t{int(c)}" for c in piv.columns]
    base = base.merge(piv.reset_index(), on=["direction", "ts_ob"])
    base["side"] = np.where(base.direction == "bull", 1, -1)
    base["prox"] = np.where(base.side > 0, base.high, base.low)
    base["distal"] = np.where(base.side > 0, base.low, base.high)
    for c in [f"t{k}" for k in range(0, 6)]:
        base[c] = pd.to_datetime(base[c], utc=True) if c in base else pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns, UTC]")
    return base

def _ts_idx(times) -> np.ndarray:
    A = arrays()
    ta = pd.DatetimeIndex(times).tz_convert("UTC").as_unit("ns").asi8
    return np.searchsorted(A["t"], ta, side="left").astype(np.int64)

# ---------------------------------------------------------------------------------------- order builders
def orders_Z(tf: str, L: int, entry: str, slm: str, delay: int = DELAY) -> pd.DataFrame:
    """Main family: limit at alert (detection) + delay. HTF: ★5 = first touch in engine window (see prereg)."""
    z = zones(tf)
    arm_col = f"t{L-1}" if tf in HTF else f"t{L}"
    z = z[z[arm_col].notna()].copy()
    if z.empty:
        return z
    z["det"] = pd.DatetimeIndex(z[arm_col])
    z["t_active"] = z["det"] + pd.Timedelta(minutes=delay)
    z["expiry_min"] = float(EXPIRY_MIN[tf] - delay)
    if tf in HTF:
        A = arrays()
        si = _ts_idx(z["t_active"])
        k = _first_touch(A["t"], A["h"], A["l"], si, (z["expiry_min"].to_numpy() * 6e10).astype(np.int64),
                         z["side"].to_numpy(np.int64), z["prox"].to_numpy(float))
        ok = k >= 0
        z = z[ok].copy(); k = k[ok]
        ttouch = A["index"][k]
        tl = pd.DatetimeIndex(z[f"t{L}"]) if f"t{L}" in z else pd.DatetimeIndex([pd.NaT] * len(z))
        already = np.asarray(tl.notna()) & np.asarray((tl + pd.Timedelta(minutes=delay)) <= ttouch)
        sess = in_win(A["mod"][k], ENG_WIN)
        z = z[already | sess].copy()
    z["level"] = z["entry_eng"] if entry == "mid" else z["prox"]
    buf = 0.05 if slm == "eng" else 0.10
    z["sl"] = z["distal"] - z["side"] * buf * z["atr"]
    z["etype"] = "limit"
    z["trend_H4"] = trend_at("H4", z["det"]); z["trend_D1"] = trend_at("D1", z["det"])
    z["zid"] = z["direction"] + "|" + z["ts_ob"].astype(str)
    return z.reset_index(drop=True)

def orders_MIX(tf: str, L: int, entry: str, slm: str, delay: int = DELAY) -> pd.DataFrame:
    """HTF zone; first touch must be in engine London/NY window; alert at the M5 close containing the touch."""
    z = zones(tf)
    arm_col = f"t{L-1}"
    z = z[z[arm_col].notna()].copy()
    z["det"] = pd.DatetimeIndex(z[arm_col])
    A = arrays()
    si = _ts_idx(z["det"] + pd.Timedelta(minutes=DELAY))      # zone watched from detection + 3 min
    k = _first_touch(A["t"], A["h"], A["l"], si, np.full(len(z), int((EXPIRY_MIN[tf] - DELAY) * 6e10), np.int64),
                     z["side"].to_numpy(np.int64), z["prox"].to_numpy(float))
    ok = k >= 0
    z = z[ok].copy(); k = k[ok]
    z = z[in_win(A["mod"][k], ENG_WIN)].copy(); k = k[in_win(A["mod"][k], ENG_WIN)]
    ttouch = A["index"][k]
    alert = ttouch.floor("5min") + pd.Timedelta(minutes=5)
    z["det"] = alert                                            # trend evaluated at the touch alert
    z["t_active"] = alert + pd.Timedelta(minutes=delay)
    if entry == "market":
        z["etype"] = "market"; z["level"] = z["prox"]; z["expiry_min"] = 0.0
    else:
        z["etype"] = "limit"; z["level"] = z["entry_eng"]; z["expiry_min"] = 60.0
    buf = 0.05 if slm == "eng" else 0.10
    z["sl"] = z["distal"] - z["side"] * buf * z["atr"]
    z["trend_H4"] = trend_at("H4", z["det"]); z["trend_D1"] = trend_at("D1", z["det"])
    z["zid"] = z["direction"] + "|" + z["ts_ob"].astype(str)
    return z.reset_index(drop=True)

# ------------------------------------------------------------------------------------------- simulation
def simulate(orders: pd.DataFrame, tps, holds, cost_mult: float = 1.0) -> pd.DataFrame:
    """Cartesian (orders x tp x hold) through common._sim. Returns filled trades with r_net / r_gross components."""
    if orders.empty:
        return pd.DataFrame()
    A = arrays()
    combos = list(itertools.product(tps, holds))
    o = orders.loc[orders.index.repeat(len(combos))].reset_index(drop=True)
    o["tp"] = np.tile([c[0] for c in combos], len(orders)).astype(float)
    o["hold"] = np.tile([c[1] for c in combos], len(orders)).astype(float)
    si = _ts_idx(o["t_active"])
    sp, cm, sl_ = costs(SYM, 0.0)
    n = len(o)
    hs = np.full(n, sp * cost_mult / 2.0); slip = np.full(n, sl_ * cost_mult)
    et = o["etype"].map({"market": 0, "limit": 1, "stop": 2}).to_numpy(np.int64)
    f, x, epx, xpx, risk, why = _sim(A["t"], A["o"], A["h"], A["l"], A["c"], si, o["side"].to_numpy(np.int64), et,
                                     o["level"].to_numpy(float), o["sl"].to_numpy(float), o["tp"].to_numpy(float),
                                     np.full(n, np.nan), (o["expiry_min"].to_numpy(float) * 6e10).astype(np.int64),
                                     (o["hold"].to_numpy(float) * 6e10).astype(np.int64), hs, slip)
    o["fill_i"] = f; o["exit_i"] = x; o["entry_px"] = epx; o["exit_px"] = xpx; o["risk"] = risk; o["why"] = why
    o = o[(why >= 1) & (why <= 4)].copy()
    if o.empty:
        return o
    fi = o["fill_i"].to_numpy(); xi = o["exit_i"].to_numpy()
    o["t_fill"] = A["index"][fi]; o["t_exit"] = A["index"][xi]
    o["fill_mod"] = A["mod"][fi]
    o["hold_min"] = (A["t"][xi] - A["t"][fi]) / 6e10 + 1.0
    sgn = o["side"].to_numpy(float)
    o["r_px"] = sgn * (o["exit_px"] - o["entry_px"]) / o["risk"]
    nts = nights(fi, xi)
    swap = np.where(sgn > 0, SWAP_LONG, SWAP_SHORT) * o["entry_px"].to_numpy() * nts * cost_mult
    o["nights"] = nts
    o["r_net"] = o["r_px"] - cm * cost_mult / o["risk"] - swap / o["risk"]
    o["cost_risk"] = (sp + cm + sl_) / o["risk"]
    tf_ = o["t_fill"]
    o["period"] = np.where(tf_ < PRE_START, "warm", np.where(tf_ < MAIN_START, "pre", np.where(tf_ < SPLIT, "train", "test")))
    o["pday"] = pd.DatetimeIndex(tf_).tz_convert("Europe/Paris").normalize()
    return o.reset_index(drop=True)

# ---------------------------------------------------------------------------------------------- metrics
def _wd(a, b) -> float:
    return float(np.busday_count(a.date(), b.date()))

def metrics(tr: pd.DataFrame, period: str, col: str = "r_net") -> dict:
    a, b = PERIODS[period]
    n = len(tr)
    if n == 0:
        return dict(n=0, per_wd=0.0, wr=np.nan, avg=np.nan, lo=np.nan, hi=np.nan, t=np.nan, pf=np.nan, maxdd=0.0,
                    streak=0, hold=np.nan, cost_risk=np.nan)
    tr = tr.sort_values("t_fill")
    r = tr[col].to_numpy(float)
    m = r.mean(); sd = r.std(ddof=1) if n > 1 else np.nan
    se = sd / math.sqrt(n) if n > 1 else np.nan
    eq = np.cumsum(r); dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    gains = r[r > 0].sum(); loss = -r[r < 0].sum()
    streak = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        streak = max(streak, cur)
    return dict(n=n, per_wd=n / _wd(a, b), wr=float((r > 0).mean()), avg=float(m),
                lo=float(m - 1.96 * se) if n > 1 else np.nan, hi=float(m + 1.96 * se) if n > 1 else np.nan,
                t=float(m / se) if n > 1 and se > 0 else np.nan, pf=float(gains / loss) if loss > 0 else np.inf,
                maxdd=dd, streak=int(streak), hold=float(tr["hold_min"].mean()), cost_risk=float(tr["cost_risk"].median()))

def quarters(tr: pd.DataFrame, col="r_net") -> dict:
    if tr.empty:
        return {}
    q = pd.DatetimeIndex(tr["t_fill"]).tz_convert("UTC").tz_localize(None).to_period("Q").astype(str)
    return {k: dict(n=int(len(g)), avg=float(g[col].mean())) for k, g in tr.groupby(q)}

def apply_filters(tr: pd.DataFrame, trend: str, session: str, fod: bool) -> pd.DataFrame:
    x = tr
    if trend != "none":
        x = x[x[f"trend_{trend}"].to_numpy() == x["side"].to_numpy()]
    if session == "LonNY":
        x = x[in_win(x["fill_mod"].to_numpy(), LONNY)]
    if fod:
        x = x.sort_values("t_fill").groupby("pday", sort=False).head(1)
    return x

# ------------------------------------------------------------------------------------------------- grid
TRENDS = ["none", "H4", "D1"]
SESSIONS = ["all", "LonNY"]

def holds_for(tf):
    return SHORT_HOLDS + LONG_HOLDS.get(tf, [])

def order_sets():
    """Yield (group, family, tf, stars, entry, sl, builder-kwargs, holds, sessions)."""
    for tf in TFS:
        for L, e, s in itertools.product((3, 4, 5), ("mid", "prox"), ("eng", "buf")):
            yield (tf, "Z", tf, L, e, s, holds_for(tf), SESSIONS)
    for tf in ("H4", "D1"):
        for L, e, s in itertools.product((3, 4, 5), ("market", "mid"), ("eng", "buf")):
            yield (f"MIX-{tf}", "MIX", tf, L, e, s, SHORT_HOLDS, ["all"])

def build(family, tf, L, e, s, delay=DELAY):
    if family == "X":
        return orders_X(tf, L, e, s, delay)
    return orders_Z(tf, L, e, s, delay) if family == "Z" else orders_MIX(tf, L, e, s, delay)

def eval_rows(tr1, tr0, meta, sessions, holds):
    rows = []
    for tp, hold, trd, ses in itertools.product((1.0, 2.0, 3.0), holds, TRENDS, sessions):
        sel1 = tr1[(tr1.tp == tp) & (tr1.hold == hold)] if not tr1.empty else tr1
        sel0 = tr0[(tr0.tp == tp) & (tr0.hold == hold)] if not tr0.empty else tr0
        for fod in (False, True):
            x1 = apply_filters(sel1, trd, ses, fod) if not sel1.empty else sel1
            x0 = apply_filters(sel0, trd, ses, fod) if not sel0.empty else sel0
            row = dict(meta, tp=tp, hold=hold, trend=trd, session=ses, fod=fod)
            for per in ("train", "test", "pre"):
                p1 = x1[x1.period == per] if not x1.empty else x1
                p0 = x0[x0.period == per] if not x0.empty else x0
                mt = metrics(p1, per)
                for k, v in mt.items():
                    row[f"{per}_{k}"] = v
                row[f"{per}_gross"] = float(p0["r_net"].mean()) if len(p0) else np.nan
            rows.append(row)
    return rows

def grid():
    allrows = []
    t0 = time.time()
    for group, fam, tf, L, e, s, holds, sessions in order_sets():
        od = build(fam, tf, L, e, s)
        tr1 = simulate(od, (1.0, 2.0, 3.0), holds, 1.0)
        tr0 = simulate(od, (1.0, 2.0, 3.0), holds, 0.0)
        meta = dict(group=group, family=fam, tf=tf, stars=L, entry=e, sl=s, n_orders=len(od))
        allrows += eval_rows(tr1, tr0, meta, sessions, holds)
        print(group, L, e, s, "orders", len(od), "fills", len(tr1) // max(1, 3 * len(holds)), f"{time.time()-t0:.0f}s", flush=True)
    g = pd.DataFrame(allrows)
    # fod variant only counts if the base config trades > 2/weekday on TRAIN (pre-registered)
    key = ["group", "family", "tf", "stars", "entry", "sl", "tp", "hold", "trend", "session"]
    base = g[~g.fod].set_index(key)["train_per_wd"]
    g = g.merge(base.rename("base_train_per_wd").reset_index(), on=key)
    g = g[(~g.fod) | (g.base_train_per_wd > 2.0)].reset_index(drop=True)
    g["cfg"] = g.apply(cfg_name, axis=1)
    g.to_csv(OUTX / "grid_full.csv", index=False)
    print("configs", len(g), f"{time.time()-t0:.0f}s")
    return g

def cfg_name(r) -> str:
    return (f"{r['group']}|{r['stars']}*|{r['entry']}|SL{r['sl']}|TP{int(r['tp'])}R|hold{int(r['hold'])}m|"
            f"trend{r['trend']}|{r['session']}" + ("|fod" if r["fod"] else ""))

# ------------------------------------------------------------------- EXPLORATORY family X (HTF, relaxed)
def orders_X(tf: str, variant: str, entry: str, slm: str, delay: int = DELAY) -> pd.DataFrame:
    z = zones(tf, "x").copy()
    if variant == "fvg":
        z = z[z["s1"].astype(bool)].copy()
    z["det"] = pd.DatetimeIndex(z["t0"])
    z["t_active"] = z["det"] + pd.Timedelta(minutes=delay)
    z["expiry_min"] = float(EXPIRY_MIN[tf] - delay)
    z["level"] = z["entry_eng"] if entry == "mid" else z["prox"]
    buf = 0.05 if slm == "eng" else 0.10
    z["sl"] = z["distal"] - z["side"] * buf * z["atr"]
    z["etype"] = "limit"
    z["trend_H4"] = trend_at("H4", z["det"]); z["trend_D1"] = trend_at("D1", z["det"])
    z["zid"] = z["direction"] + "|" + z["ts_ob"].astype(str)
    return z.reset_index(drop=True)

XGROUPS = ["X-H4", "X-D1", "X-W"]

def grid_x():
    rows = []; t0 = time.time()
    for tf in ("H4", "D1", "W"):
        for v, e, s_ in itertools.product(("fvg", "any"), ("mid", "prox"), ("eng", "buf")):
            od = orders_X(tf, v, e, s_)
            holds = holds_for(tf)
            tr1 = simulate(od, (1.0, 2.0, 3.0), holds, 1.0); tr0 = simulate(od, (1.0, 2.0, 3.0), holds, 0.0)
            meta = dict(group=f"X-{tf}", family="X", tf=tf, stars=v, entry=e, sl=s_, n_orders=len(od))
            rows += eval_rows(tr1, tr0, meta, SESSIONS, holds)
            print("X", tf, v, e, s_, "orders", len(od), f"{time.time()-t0:.0f}s", flush=True)
    g = pd.DataFrame(rows)
    key = ["group", "family", "tf", "stars", "entry", "sl", "tp", "hold", "trend", "session"]
    base = g[~g.fod].set_index(key)["train_per_wd"]
    g = g.merge(base.rename("base_train_per_wd").reset_index(), on=key)
    g = g[(~g.fod) | (g.base_train_per_wd > 2.0)].reset_index(drop=True)
    g["cfg"] = g.apply(cfg_name, axis=1)
    g.to_csv(OUTX / "grid_full_X_exploratory.csv", index=False)
    print("X configs", len(g))

# ------------------------------------------------------------------------------------- selection (TRAIN)
GROUPS = TFS + ["MIX-H4", "MIX-D1"]

def _cfg_from_row(r):
    return dict(family=r["family"], tf=r["tf"], L=(r["stars"] if r["family"] == "X" else int(r["stars"])), e=r["entry"], s=r["sl"], tp=float(r["tp"]),
                hold=float(r["hold"]), trend=r["trend"], session=r["session"], fod=bool(r["fod"]))

def run_cfg(c, cost_mult=1.0, delay=DELAY) -> pd.DataFrame:
    od = build(c["family"], c["tf"], c["L"], c["e"], c["s"], delay)
    tr = simulate(od, (c["tp"],), (c["hold"],), cost_mult)
    return apply_filters(tr, c["trend"], c["session"], c["fod"]) if not tr.empty else tr

def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, (np.floating, float)):
        return None if (np.isnan(d) or np.isinf(d)) else float(d)
    if isinstance(d, np.integer):
        return int(d)
    return d

def select(exploratory: bool = False):
    from scipy.stats import norm
    g = pd.read_csv(OUTX / ("grid_full_X_exploratory.csv" if exploratory else "grid_full.csv"))
    sfx = "_X_exploratory" if exploratory else ""
    groups = XGROUPS if exploratory else GROUPS
    K = len(g); bonf = float(norm.isf(0.025 / K))
    out = dict(K=K, bonferroni_t=bonf, groups={})
    top_rows, summ = [], []
    for grp in groups:
        x = g[g.group == grp]
        if x.empty:
            continue
        elig = x[(x.train_n >= 40) & (x.train_per_wd <= 3.0)]
        flag = ""
        if elig.empty:
            elig = x[(x.train_n >= 20) & (x.train_per_wd <= 3.0)]; flag = "insufficient sample (n>=20 fallback)"
        summ.append(dict(group=grp, configs=len(x), eligible=len(elig),
                         train_net_pos=int((x.train_avg > 0).sum()), test_net_pos=int((x.test_avg > 0).sum()),
                         eligible_train_net_pos=int((elig.train_avg > 0).sum()), eligible_test_net_pos=int((elig.test_avg > 0).sum()),
                         train_gross_pos=int((x.train_gross > 0).sum()), test_gross_pos=int((x.test_gross > 0).sum()),
                         median_train_net=float(elig.train_avg.median()) if len(elig) else np.nan,
                         median_test_net=float(elig.test_avg.median()) if len(elig) else np.nan,
                         best_train_t=float(elig.train_t.max()) if len(elig) else np.nan))
        if elig.empty:
            out["groups"][grp] = dict(verdict="NO ELIGIBLE CONFIG", flag="n<20"); continue
        elig = elig.sort_values("train_t", ascending=False)
        for rank, (_, r) in enumerate(elig.head(5).iterrows(), 1):
            top_rows.append(dict(group=grp, rank=rank, cfg=r["cfg"], train_n=r.train_n, train_avg=r.train_avg, train_t=r.train_t,
                                 test_n=r.test_n, test_per_wd=r.test_per_wd, test_avg=r.test_avg, test_lo=r.test_lo,
                                 test_hi=r.test_hi, test_pf=r.test_pf, train_gross=r.train_gross, test_gross=r.test_gross))
        w = elig.iloc[0]; c = _cfg_from_row(w)
        tr1 = run_cfg(c, 1.0); tr0 = run_cfg(c, 0.0); tr15 = run_cfg(c, 1.5); trd5 = run_cfg(c, 1.0, delay=5)
        d = dict(cfg=w["cfg"], rules=c, flag=flag, train_t=float(w.train_t), clears_bonferroni=bool(abs(w.train_t) > bonf))
        for per in ("train", "test", "pre"):
            p1 = tr1[tr1.period == per] if len(tr1) else tr1
            d[per] = metrics(p1, per)
            d[per]["gross"] = float(tr0[tr0.period == per]["r_net"].mean()) if len(tr0) and (tr0.period == per).any() else np.nan
            d[per]["cost15"] = float(tr15[tr15.period == per]["r_net"].mean()) if len(tr15) and (tr15.period == per).any() else np.nan
            d[per]["delay5"] = float(trd5[trd5.period == per]["r_net"].mean()) if len(trd5) and (trd5.period == per).any() else np.nan
            d[per]["quarters"] = quarters(p1)
            d[per]["exit_mix"] = (p1["why"].map({1: "tp", 2: "sl", 3: "time", 4: "eod"}).value_counts(normalize=True).round(3).to_dict()
                                  if len(p1) else {})
        te = d["test"]
        qpos = sum(1 for v in te["quarters"].values() if v["avg"] > 0)
        d["test_quarters_pos"] = f"{qpos}/{len(te['quarters'])}"
        if not te["n"] or not (te["avg"] > 0):
            v = "FAIL"
        elif te["lo"] > 0 and te["cost15"] > 0 and te["delay5"] > 0 and qpos >= 3 and te["n"] >= 20:
            v = "VIABLE"
        else:
            v = "PROMISING (TEST>0 but not robust)"
        d["verdict"] = v
        out["groups"][grp] = d
        cols = ["t_fill", "t_exit", "side", "level", "sl", "entry_px", "exit_px", "risk", "why", "hold_min", "nights",
                "r_px", "r_net", "cost_risk", "period", "zid", "det"]
        tr1[[c_ for c_ in cols if c_ in tr1]].to_csv(OUTX / f"trades_winner_{grp}.csv", index=False)
        print(grp, v, w["cfg"], "train", round(d["train"]["avg"], 3), "test", te["avg"], flush=True)
    pd.DataFrame(top_rows).to_csv(OUTX / f"top5_per_group_test{sfx}.csv", index=False)
    pd.DataFrame(summ).to_csv(OUTX / f"group_summary{sfx}.csv", index=False)
    (OUTX / f"winners{sfx}.json").write_text(json.dumps(_clean(out), indent=1, default=str))
    return out

# ------------------------------------------------------------------------------------- random baseline
def baseline():
    rng = np.random.default_rng(11)
    A = arrays()
    idx = A["index"]; t = idx[idx >= PRE_START]
    loc = t.tz_convert("Europe/Paris")
    day = loc.normalize(); wk = loc.dayofweek < 5
    mod = (loc.hour * 60 + loc.minute).to_numpy()
    rows = []
    for ses in ("all", "LonNY"):
        m = wk & (in_win(mod, LONNY) if ses == "LonNY" else True)
        tt = pd.Series(t[m]); dd = pd.Series(day[m])
        pick = tt.groupby(dd.values).apply(lambda s: s.sample(min(3, len(s)), random_state=int(rng.integers(1e9))))
        picks = pd.DatetimeIndex(pick.values)
        picks = picks.tz_localize("UTC") if picks.tz is None else picks.tz_convert("UTC")
        for tf in TFS:
            z = zones(tf); z = z[z["t3"].notna() if tf not in HTF else z["t2"].notna()]
            k = float(np.nanmedian(np.abs(z["entry_eng"] - z["sl_eng"]) / z["atr"]))
            atr = asof(tf, picks, "atr"); si = _ts_idx(picks); px = A["o"][np.clip(si, 0, len(A["o"]) - 1)]
            side = rng.choice([-1, 1], len(picks))
            od = pd.DataFrame(dict(t_active=picks, side=side, etype="market", level=px, sl=px - side * k * atr, expiry_min=0.0))
            od = od[np.isfinite(od.sl)].reset_index(drop=True)
            holds = holds_for(tf)
            for cmult in (1.0, 0.0):
                tr = simulate(od, (1.0, 2.0, 3.0), holds, cmult)
                for (tp, hold), x in tr.groupby(["tp", "hold"]):
                    for per in ("train", "test"):
                        p = x[x.period == per]
                        mt = metrics(p, per)
                        rows.append(dict(session=ses, tf=tf, sl_atr_mult=k, tp=tp, hold=hold, cost=cmult, period=per,
                                         n=mt["n"], avg=mt["avg"], lo=mt["lo"], hi=mt["hi"], wr=mt["wr"], cost_risk=mt["cost_risk"]))
            print("baseline", ses, tf, round(k, 2), flush=True)
    b = pd.DataFrame(rows); b.to_csv(OUTX / "random_baseline.csv", index=False)
    return b

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "detect":
        detect(sys.argv[2:] or TFS)
    elif cmd == "detect_x":
        detect(["H4", "D1", "W"], mode="x")
    elif cmd == "grid_x":
        grid_x()
    elif cmd == "select_x":
        select(exploratory=True)
    elif cmd == "grid":
        grid()
    elif cmd == "select":
        select()
    elif cmd == "baseline":
        baseline()
