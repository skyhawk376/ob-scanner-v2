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
    tf, a, b = args
    from app.engine.detect import detect_zones
    from app.engine.params import EngineParams
    if tf not in _HB:
        _HB.clear(); _HB[tf] = pd.read_parquet(CACHE / f"bars_{tf}.parquet")
    h = _HB[tf]
    lb = LOOKBACK[tf]
    p = EngineParams(pivot_n=PIVOT[tf], lookback=lb, entry_mode="mid")
    min_s = 2 if tf in HTF else 3
    seen, out = set(), []
    for j in range(a, min(b, len(h))):
        sub = h.iloc[max(0, j - lb - 2): j + 1]
        for z in detect_zones(sub, symbol=SYM, tf=ENG_TF[tf], params=p, min_score=min_s, require_fresh=True, require_fvg=True):
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

def detect(tfs):
    tasks = []
    for tf in tfs:
        b = bars(tf)[["open", "high", "low", "close"]]
        b.to_parquet(CACHE / f"bars_{tf}.parquet")
        chunk = 8000
        for a in range(WARM[tf], len(b), chunk):
            tasks.append((tf, a, a + chunk))
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
        zs.to_pickle(CACHE / f"zones_{tf}.pkl")
        print("saved", tf, len(zs), zs.groupby("level").size().to_dict() if len(zs) else {}, f"{time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "detect":
    detect(sys.argv[2:] or TFS)
