"""TEST evaluation (read once) of selection.json: selected + top-5 TRAIN candidates, random baselines, breakdowns."""
import json
import numpy as np, pandas as pd
from sim import EVENTS, ZONES, RES, C, part, run, apply_filter, row, simulate

sel = json.loads((RES / "selection.json").read_text())
EV = part(pd.read_parquet(EVENTS), "test"); Z = pd.read_parquet(ZONES)
G = pd.read_csv(RES / "train_grid.csv").set_index("cfg")
rng = np.random.default_rng(70)

def parse(cfg):
    e, tp, hold, be, f = cfg.split("|")
    return e, float(tp[2:]), hold, 0.5 if be == "be1" else 0.0, f

def random_baseline(t, tp, hold, be, ndraw=200):
    W = {"1h": 60, "3h": 180}[hold]
    reqs = []
    for d in range(ndraw):
        u = np.floor(rng.uniform(0, W, len(t)))
        reqs.append(pd.DataFrame(dict(sym=t.sym.values, t_active=pd.DatetimeIndex(t.t0) + pd.to_timedelta(u, "min"),
                                      side=t.side.values, etype="market", level=t.entry_px.values, sl=t.sl.values,
                                      tp_r=tp, expiry_min=1.0, hold_min=float(W), be=be, draw=d)))
    r = simulate(pd.concat(reqs, ignore_index=True), 1.0)
    r = r[r.side * (r.entry_px - r.sl) > 0]
    g = r.groupby("draw")
    return g.r_net.mean(), g.r_net.apply(lambda x: (x > 0).mean())

cfgs = [sel["selected"]] + [c for c in sel["top5"] if c != sel["selected"]]
out, keep = [], {}
for cfg in cfgs:
    e, tp, hold, be, f = parse(cfg)
    t = apply_filter(run(EV, Z, e, hold, tp, be), f)
    keep[cfg] = t
    r = row(t, "test"); r["cfg"] = cfg
    r["train_wr"] = G.loc[cfg, "wr"]; r["train_net"] = G.loc[cfg, "net"]; r["train_n"] = G.loc[cfg, "n"]
    r["gross_lo"] = t.r_gross.mean() - 1.96 * t.r_gross.std() / np.sqrt(len(t))
    r["gross_hi"] = t.r_gross.mean() + 1.96 * t.r_gross.std() / np.sqrt(len(t))
    r["wr_gross"] = (t.r_gross > 0).mean()
    r["be_wr_net"] = 1 / (1 + tp)  # pre-cost breakeven WR (info)
    r["avg_cost_r"] = t.cost_r.mean()
    rb, rw = random_baseline(t, tp, hold, be)
    r["rand_mean"] = rb.mean(); r["rand_p95"] = rb.quantile(0.95); r["rand_wr"] = rw.mean()
    r["wr70"] = r["wr"] >= 0.70; r["profitable"] = r["lo"] > 0; r["beats_random"] = r["net"] > r["rand_p95"]
    out.append(r)
tab = pd.DataFrame(out).set_index("cfg")
tab.to_csv(RES / "test_table.csv", float_format="%.4f")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
print(tab.round(3).to_string())

t = keep[sel["selected"]]
br = []
for by in ("tf", "group"):
    for k, g in t.groupby(by):
        r = row(g, "test"); r.update(by=by, key=k); br.append(r)
B = pd.DataFrame(br); B.to_csv(RES / "test_breakdown.csv", index=False, float_format="%.4f")
print(B.round(3).to_string(index=False))
print("exit mix:", t.why.value_counts(normalize=True).round(3).to_dict())
w = t[t.r_net > 0].r_net.mean(); l = t[t.r_net <= 0].r_net.mean()
print(f"avg net win {w:.3f}R, avg net loss {l:.3f}R, avg cost {t.cost_r.mean():.3f}R")
t.to_parquet(RES / "test_trades_selected.parquet")
