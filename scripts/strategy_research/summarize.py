"""After select_eval.py: gross (zero-cost) metrics of winners + per-family summary over ALL configs (train & test).
Writes family_summary.csv, grid_full_{fam}.csv, winners_gross.json."""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
from select_eval import variant
from common import split, metrics, TRAIN, TEST, OUT, ROOT

sel = json.load(open(OUT / "selection.json"))
res = {}
for name in sel["winners"]:
    fam = name.split("|")[0].split("=")[1]
    a, b = split(variant(name, fam, cost=0.0))
    res[name] = dict(train_gross=metrics(a, TRAIN)["avg"], test_gross=metrics(b, TEST)["avg"])
json.dump(res, open(OUT / "winners_gross.json", "w"), indent=1)
rows = []
for fam in ["A_OB", "B_SWEEP", "C_ORB", "D_FVG", "E_PDHL"]:
    tr = pd.read_csv(OUT / f"grid_train_{fam}.csv"); te = pd.read_csv(ROOT / f"data/cache/strategy_research/grid_test_{fam}.csv")
    g0 = pd.read_csv(OUT / f"grid_train_{fam}_cost0.csv")[["name", "tr_avg"]].rename(columns={"tr_avg": "tr_gross"})
    g0t = pd.read_csv(ROOT / f"data/cache/strategy_research/grid_test_{fam}_cost0.csv")[["name", "te_avg"]].rename(columns={"te_avg": "te_gross"})
    d = tr.merge(te, on="name").merge(g0, on="name").merge(g0t, on="name")
    rows.append(dict(family=fam, configs=len(d), train_net_pos=int((d.tr_avg > 0).sum()), test_net_pos=int((d.te_avg > 0).sum()),
                     both_net_pos=int(((d.tr_avg > 0) & (d.te_avg > 0)).sum()),
                     best_train_net=round(d.tr_avg.max(), 3), median_train_net=round(d.tr_avg.median(), 3), median_test_net=round(d.te_avg.median(), 3),
                     best_train_gross=round(d.tr_gross.max(), 3), median_train_gross=round(d.tr_gross.median(), 3), median_test_gross=round(d.te_gross.median(), 3),
                     train_gross_pos=int((d.tr_gross > 0).sum()), both_gross_pos=int(((d.tr_gross > 0) & (d.te_gross > 0)).sum())))
    d.to_csv(OUT / f"grid_full_{fam}.csv", index=False)
s = pd.DataFrame(rows); s.to_csv(OUT / "family_summary.csv", index=False); print(s.to_string(index=False)); print(res)

# 0.5x cost sensitivity of the winners (+ X2 at 0.3x / 0.5x) -> cost_half_sensitivity.json
import exploratory as X
from common import simulate
half = {}
for name in sel["winners"] + ["family=D_FVG|window=US|trend=H4|entry=prox|sl=c1|tp=2|fod"]:
    fam = name.split("|")[0].split("=")[1]
    a, b = split(variant(name, fam, cost=0.5))
    half[name] = (round(metrics(a, TRAIN)["avg"], 3), round(metrics(b, TEST)["avg"], 3), round(metrics(b, TEST)["lo"], 3))
for cm in (0.3, 0.5):
    a, b = split(simulate(X.x2_requests(0.0), cost_mult=cm))
    half[f"X2_floor0_cost{cm}"] = (round(metrics(a, TRAIN)["avg"], 3), round(metrics(b, TEST)["avg"], 3),
                                   round(metrics(b, TEST)["lo"], 3), round(metrics(b, TEST)["hi"], 3))
json.dump(half, open(OUT / "cost_half_sensitivity.json", "w"), indent=1)
print(half)
