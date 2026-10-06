"""EXPLORATORY (not pre-registered) checks on the near-miss (family C winner). Cannot count as evidence."""
import json
import numpy as np, pandas as pd
import core as C
from grid import load, SPLIT_NS, WK_TRAIN, WK_TEST

d = load(cost=1.0, mgmt=0)
out = {}
WIN = json.loads((C.OUT / "selection.json").read_text())["C"]["winner"]   # e.g. C|H4|FVG|s3|tr50|prox|2R|2d
_, W_TF, W_DEF, W_ST, W_TR, W_EN, W_TP, W_HO = WIN.split("|")
out["C_winner"] = WIN
def st(x):
    r = x.r_net.to_numpy(float); n = len(r)
    if n < 2: return dict(n=n, avg=float(r.mean()) if n else None)
    se = r.std(ddof=1) / np.sqrt(n)
    return dict(n=n, avg=round(float(r.mean()), 3), lo=round(float(r.mean() - 1.96 * se), 3), hi=round(float(r.mean() + 1.96 * se), 3))
# 1. same rules on other asset groups (is the effect index-specific?)
m = (d.fam == "Z") & (d.tf == W_TF) & (d.fvg if W_DEF == "FVG" else True) & ((d.score4 >= 3) if W_ST == "s3" else True) & (d[W_TR] == d.side) & (d.entry == W_EN) & (d.tp == W_TP) & (d.hold == W_HO)
x = d[m]
out["C_rules_by_group"] = {g: {p: st(xx[(xx.t_fill < SPLIT_NS) == (p == "train")]) for p in ("train", "test")} for g, xx in x.groupby("group")}
# 2. Paris hour of fills (indices) and test by session bucket
xi = x[x.group == "INDICES"].copy()
hr = pd.to_datetime(xi.t_fill, utc=True).dt.tz_convert("Europe/Paris").dt.hour
xi["sess"] = np.where((hr >= 8) & (hr < 22), "08-22 Paris", "22-08 Paris")
out["C_by_fill_session"] = {s: {p: st(xx[(xx.t_fill < SPLIT_NS) == (p == "train")]) for p in ("train", "test")} for s, xx in xi.groupby("sess")}
# 3. all 96 H4 configs of family C pooled view (configs positive on TEST / on TRAIN)
g = pd.read_csv(C.OUT / "grid_C.csv"); h4 = g[g.tf == "H4"]
out["C_H4_configs"] = dict(K=len(h4), train_pos=int((h4.train_avg > 0).sum()), test_pos=int((h4.test_avg > 0).sum()),
                           test_lo_pos=int((h4.test_lo > 0).sum()), mean_train=round(h4.train_avg.mean(), 3), mean_test=round(h4.test_avg.mean(), 3))
h1 = g[g.tf == "H1"]
out["C_H1_configs"] = dict(K=len(h1), train_pos=int((h1.train_avg > 0).sum()), test_pos=int((h1.test_avg > 0).sum()),
                           mean_train=round(h1.train_avg.mean(), 3), mean_test=round(h1.test_avg.mean(), 3))
# 4. winner with 3h cap (same rules) and stats
e = pd.read_csv(C.OUT / "grid_EC.csv")
out["C_winner_3h"] = e[e.cfg == "EC|" + "|".join(WIN.split("|")[1:-1]) + "|3h"].iloc[0][["train_n", "train_avg", "train_t", "test_n", "test_avg", "test_lo", "test_hi", "test_wr", "test_pf"]].to_dict()
# 5. bootstrap of the C winner TEST mean (trade resampling) and concurrency
w = x[x.group == "INDICES"]; te = w[w.t_fill >= SPLIT_NS].r_net.to_numpy(float)
rng = np.random.default_rng(1); bs = rng.choice(te, (20000, len(te))).mean(1)
out["C_winner_test_bootstrap"] = dict(p_mean_le_0=float((bs <= 0).mean()), q05=float(np.quantile(bs, 0.05)), q50=float(np.median(bs)))
# 6. pooled train+test t-stat
r = w.r_net.to_numpy(float); out["C_winner_pooled"] = dict(n=len(r), avg=round(float(r.mean()), 3), t=round(float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), 2))
# trades of the winner for the record
w.sort_values("t_fill").assign(t_fill=lambda z: pd.to_datetime(z.t_fill, utc=True), t_exit=lambda z: pd.to_datetime(z.t_exit, utc=True)).to_csv(C.OUT / "trades_winner_C.csv", index=False)
(C.OUT / "exploratory.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps(out, indent=1, default=float))
