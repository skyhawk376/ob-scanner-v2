"""OB 5★ on M5/M15/M30 — causal walk-forward detection with the repo engine (detect.py unchanged).
Params adapted per TF: pivot_n=3, lookback=300 bars (M5 ≈ 25h, M15 ≈ 3 days, M30 ≈ 6 days), other params = engine defaults.
At every bar j: detect_zones(bars[j-302 : j+1]) -> engine drops bar j as 'forming' -> zone known at open of bar j.
First appearance per (direction, ts_ob, level) with level in {4,5} is recorded (score >= level, fresh, FVG).
Bars are split in chunks processed in parallel; merge keeps the earliest det_time (identical to a serial walk).
Output: data/cache/strategy_research/ob_zones_{TF}.pkl
Usage: .venv/bin/python scripts/strategy_research/ob_lowtf_detect.py M30 M15 M5
"""
from __future__ import annotations
import pickle, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ALL, ROOT, resample  # noqa: E402

LOOKBACK = 300
WARM = 400
CHUNK = 15000
RULE = {"M5": "5min", "M15": "15min", "M30": "30min"}

def run(args):
    sym, tf, a, b = args
    from app.engine.detect import detect_zones
    from app.engine.params import EngineParams
    h = resample(sym, RULE[tf])
    p = EngineParams(pivot_n=3, lookback=LOOKBACK, entry_mode="mid")
    seen, zones = set(), []
    for j in range(a, min(b, len(h))):
        sub = h.iloc[max(0, j - LOOKBACK - 2): j + 1]
        for z in detect_zones(sub, symbol=sym, tf=tf, params=p, min_score=4, require_fresh=True, require_fvg=True):
            for lvl in (4, 5):
                if z.score < lvl:
                    continue
                key = (z.direction, z.ts_ob, lvl)
                if key in seen:
                    continue
                seen.add(key)
                zones.append(dict(sym=sym, tf=tf, direction=z.direction, ts_ob=z.ts_ob, level=lvl, score=z.score,
                                  low=z.low, high=z.high, open=z.open, atr=z.atr, entry_eng=z.entry, sl_eng=z.sl,
                                  det_time=h.index[j], stars=(z.star1_fvg, z.star2_trend, z.star3_fib, z.star4_liquidity, z.star5_session)))
    return sym, tf, zones

if __name__ == "__main__":
    tfs = sys.argv[1:] or ["M30", "M15", "M5"]
    tasks = []
    for tf in tfs:
        for sym in ALL:
            n = len(resample(sym, RULE[tf]))
            for a in range(WARM, n, CHUNK):
                tasks.append((sym, tf, a, a + CHUNK))
    print("tasks", len(tasks), flush=True)
    res = {tf: {} for tf in tfs}
    t0 = time.time(); done = 0
    with ProcessPoolExecutor(8) as ex:
        for sym, tf, z in ex.map(run, tasks, chunksize=1):
            res[tf].setdefault(sym, []).extend(z)
            done += 1
            if done % 20 == 0:
                print(f"{done}/{len(tasks)} {time.time()-t0:.0f}s", flush=True)
    for tf in tfs:
        out = {}
        for sym, zs in res[tf].items():
            best = {}
            for z in zs:
                k = (z["direction"], z["ts_ob"], z["level"])
                if k not in best or z["det_time"] < best[k]["det_time"]:
                    best[k] = z
            out[sym] = sorted(best.values(), key=lambda z: z["det_time"])
        p = ROOT / f"data/cache/strategy_research/ob_zones_{tf}.pkl"
        p.write_bytes(pickle.dumps(out))
        print("saved", tf, sum(len(v) for v in out.values()), flush=True)
