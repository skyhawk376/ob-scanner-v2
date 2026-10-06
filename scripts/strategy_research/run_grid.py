"""Run the pre-registered grid for one or more families. Saves per-config trades (cache) and a TRAIN summary.
TEST metrics are computed and stored in a separate file but the selection (select.py) only uses TRAIN columns.
Usage: .venv/bin/python scripts/strategy_research/run_grid.py B_SWEEP C_ORB D_FVG E_PDHL A_OB
"""
from __future__ import annotations
import json, sys, time, warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
import families as F
from common import OUT, ROOT, TEST, TRAIN, metrics, simulate, split

TR_DIR = ROOT / "data/cache/strategy_research/trades"
TR_DIR.mkdir(parents=True, exist_ok=True)

def cfg_name(cfg: dict) -> str:
    return "|".join(f"{k}={v}" for k, v in cfg.items())

def post(tr: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """OCO (first fill wins; same-minute tie -> worse outcome) and fill-session filter (OB)."""
    if tr.empty:
        return tr
    if "oco" in tr.columns and tr["oco"].notna().any():
        tr = tr.sort_values(["t_fill", "r_net"]).groupby("oco", sort=False).head(1)
    if cfg.get("session") == "0818":
        loc = pd.DatetimeIndex(tr["t_fill"]).tz_convert("Europe/Paris")
        m = loc.hour * 60 + loc.minute
        tr = tr[(m >= F.SESS[0]) & (m < F.SESS[1])]
    return tr.sort_values("t_fill").reset_index(drop=True)

def run_cfg(args):
    fam, cfg, hold, cost_mult, delay = args
    F.DELAY = delay
    req = F.FAMILIES[fam][1](cfg)
    if req.empty:
        return cfg, None
    req["hold_min"] = float(hold)
    tr = post(simulate(req, cost_mult=cost_mult), cfg)
    return cfg, tr

def summarize(cfg, tr):
    a, b = split(tr)
    row = dict(name=cfg_name(cfg), **cfg)
    for tag, part, per in (("tr", a, TRAIN), ("te", b, TEST)):
        m = metrics(part, per)
        row.update({f"{tag}_{k}": v for k, v in m.items()})
    return row

def main(fams):
    import os
    cost = float(os.environ.get("COST", 1.0))
    sfx = "" if cost == 1.0 else f"_cost{cost:g}"
    jobs = [(fam, cfg, 60, cost, 3) for fam in fams for cfg in F.FAMILIES[fam][0]()]
    rows = []
    t0 = time.time()
    with ProcessPoolExecutor(int(__import__("os").environ.get("WORKERS", 6))) as ex:
        for cfg, tr in ex.map(run_cfg, jobs, chunksize=1):
            if tr is None:
                continue
            if not sfx:
                tr.to_parquet(TR_DIR / (cfg_name(cfg).replace("|", "__").replace("=", "-") + ".parquet"))
            rows.append(summarize(cfg, tr))
            print(f"{time.time()-t0:6.0f}s {cfg_name(cfg)} train n={rows[-1]['tr_n']} avg={rows[-1]['tr_avg']:.3f} t={rows[-1]['tr_t']:.2f}", flush=True)
    df = pd.DataFrame(rows)
    for fam in fams:
        d = df[df.family == fam]
        tr_cols = [c for c in d.columns if not c.startswith("te_")]
        d[tr_cols].to_csv(OUT / f"grid_train_{fam}{sfx}.csv", index=False)
        d[["name"] + [c for c in d.columns if c.startswith("te_")]].to_csv(ROOT / f"data/cache/strategy_research/grid_test_{fam}{sfx}.csv", index=False)

if __name__ == "__main__":
    main(sys.argv[1:])
