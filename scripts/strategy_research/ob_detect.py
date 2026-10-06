"""Family A — causal walk-forward OB 5-star detection on long H1 history using the repo engine
(backend/app/engine/detect.py, unchanged). At every H1 bar j we call detect_zones on the last 502 bars
(engine drops the last bar as 'forming', so it sees bars <= j-1; lookback 500 as live). The first time a
zone (direction, ts_ob) appears with score >= 3 (fresh + FVG required) is recorded with its stars at that time.
The zone is therefore known at det_time = open time of bar j (= close of bar j-1).
Output: data/cache/strategy_research/ob_zones.pkl
"""
from __future__ import annotations
import pickle, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ALL, ROOT, resample  # noqa: E402

WARM = 300

def run(sym: str):
    from app.engine.detect import detect_zones
    from app.engine.params import EngineParams
    h = resample(sym, "1h")
    p = EngineParams(pivot_n=3, lookback=500, entry_mode="mid")
    seen, zones = set(), []
    t0 = time.time()
    for j in range(WARM, len(h)):
        sub = h.iloc[max(0, j - 502): j + 1]
        for z in detect_zones(sub, symbol=sym, tf="H1", params=p, min_score=3, require_fresh=True, require_fvg=True):
            key = (z.direction, z.ts_ob)
            if key in seen:
                continue
            seen.add(key)
            d = z.to_dict()
            d["det_time"] = h.index[j]
            zones.append(d)
    print(sym, len(h), "zones", len(zones), f"{time.time()-t0:.0f}s", flush=True)
    return sym, zones

if __name__ == "__main__":
    syms = sys.argv[1:] or ALL
    res = {}
    with ProcessPoolExecutor(6) as ex:
        for sym, z in ex.map(run, syms):
            res[sym] = z
    out = ROOT / "data/cache/strategy_research/ob_zones.pkl"
    out.write_bytes(pickle.dumps(res))
    print("saved", out, sum(len(v) for v in res.values()))
