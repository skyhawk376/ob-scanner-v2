"""Crypto/M5/15-17 Paris subset (PREREG_WR70_CRYPTO_1517.md). `train` -> grid+selection; `test` -> all configs on TEST."""
import sys, json
import numpy as np, pandas as pd
from sim import EVENTS, ZONES, RES, C, part, run, row, simulate

STAGE = sys.argv[1]
OUT = RES / "crypto1517"; OUT.mkdir(exist_ok=True)
Z = pd.read_parquet(ZONES)
EV = pd.read_parquet(EVENTS).join(Z[["tf"]], on="zid")
h = pd.DatetimeIndex(EV.t0).tz_convert("Europe/Paris").hour
EV = EV[EV.sym.isin(["BTC", "ETH", "SOL"]) & (EV.tf == "M5") & (h >= 15) & (h < 17)].drop(columns="tf")
EV = part(EV, STAGE)
FILT = ["all", "cost10", "BTC", "ETH", "SOL"]
def filt(t, f):
    if f == "all": return t
    if f == "cost10": return t[t.cost_r <= 0.10]
    return t[t.sym == f]
rng = np.random.default_rng(1517)
def rand(t, tp, hold):
    if len(t) == 0: return np.nan, np.nan
    W = {"1h": 60, "3h": 180}[hold]; reqs = []
    for d in range(200):
        u = np.floor(rng.uniform(0, W, len(t)))
        reqs.append(pd.DataFrame(dict(sym=t.sym.values, t_active=pd.DatetimeIndex(t.t0) + pd.to_timedelta(u, "min"),
                    side=t.side.values, etype="market", level=t.entry_px.values, sl=t.sl.values, tp_r=tp,
                    expiry_min=1.0, hold_min=float(W), draw=d)))
    r = simulate(pd.concat(reqs, ignore_index=True), 1.0); r = r[r.side * (r.entry_px - r.sl) > 0]
    m = r.groupby("draw").r_net.mean(); return m.mean(), m.quantile(0.95)
rows = []
for e in ("E1", "E2", "E3"):
    for tp in (0.3, 0.5, 0.75, 1.0):
        for hold in ("1h", "3h"):
            T = run(EV, Z, e, hold, tp, 0.0)
            for f in FILT:
                t = filt(T, f); r = row(t, STAGE)
                r.update(cfg=f"{e}|tp{tp}|{hold}|{f}", gross_wr=(t.r_gross > 0).mean() if len(t) else np.nan,
                         cost_r=t.cost_r.mean() if len(t) else np.nan)
                if STAGE == "test":
                    r["rand_mean"], r["rand_p95"] = rand(t, tp, hold)
                rows.append(r)
G = pd.DataFrame(rows).set_index("cfg")
G.to_csv(OUT / f"{STAGE}_grid.csv", float_format="%.4f")
pd.set_option("display.width", 250)
if STAGE == "train":
    el = G[(G.wr >= 0.72) & (G.n >= 100)].sort_values("net", ascending=False)
    fb = G[G.n >= 100].sort_values("wr", ascending=False)
    sel = dict(selected=(el if len(el) else fb).index[0], eligible=bool(len(el)), n_eligible=len(el),
               top5=list((el if len(el) else fb).index[:5]))
    (OUT / "selection.json").write_text(json.dumps(sel, indent=1)); print(json.dumps(sel, indent=1))
print(G.sort_values("net", ascending=False).round(3).to_string())
