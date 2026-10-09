#!/usr/bin/env python3
"""TEST evaluation of the pre-selected configs (results/selection.json), random-entry baselines, breakdowns."""
import json, math
import numpy as np, pandas as pd
from common_re import RES, FAMS, C, part, row, compose_t6

sel = json.loads((RES / "selection.json").read_text())
TR = pd.read_parquet(RES / "trades.parquet"); EV = pd.read_parquet(RES / "events.parquet")
tr, ev = part(TR, "test"), part(EV, "test")
picks = {f: sel[f] for f in FAMS}
sets = {"T0 (1h)": tr[tr.cfg == "T0|limit|zone|1h"], "T0 (3h)": tr[tr.cfg == "T0|limit|zone|3h"],
        "T0+3min latency (3h, info)": tr[tr.cfg == "T0lat|limit|zone|3h"]}
for f, c in picks.items():
    sets[f"{f}: {c}"] = tr[tr.cfg == c]
t6 = compose_t6(ev, tr, sel["T6_reversal_part"])
sets[f"T6: {sel['T6_reversal_part']} else T5a"] = t6

rng = np.random.default_rng(11)


def random_baseline(t, ndraw=200):
    W = t.hold.map({"1h": 60, "3h": 180}).to_numpy()
    reqs = []
    for d in range(ndraw):
        u = rng.uniform(0, W)
        reqs.append(pd.DataFrame(dict(sym=t.sym.values, t_active=pd.DatetimeIndex(t.t0) + pd.to_timedelta(np.floor(u), "min"),
                                      side=t.side.values, etype="market", level=t.entry_px.values, sl=t.sl.values,
                                      tp_r=2.0, expiry_min=1, hold_min=t.hold_min.values, draw=d)))
    r = C.simulate(pd.concat(reqs, ignore_index=True), cost_mult=1.0)
    r = r[r.side * (r.entry_px - r.sl) > 0]
    return r.groupby("draw").r_net.mean()


out = []
base = {"1h": sets["T0 (1h)"], "3h": sets["T0 (3h)"]}
for name, t in sets.items():
    r = row(t, "test")
    r["name"] = name
    if not name.startswith("T0"):
        hold = t.hold.iloc[0]
        rb = random_baseline(t)
        r["rand_p95"] = rb.quantile(0.95); r["rand_mean"] = rb.mean()
        b = base[hold]
        d = t.r_net.mean() - b.r_net.mean()
        se = math.sqrt(t.r_net.var() / len(t) + b.r_net.var() / len(b))
        r["vs_T0"] = d; r["vs_T0_lo"] = d - 1.96 * se; r["vs_T0_hi"] = d + 1.96 * se
        r["PASS"] = bool(r["lo"] > 0 and r["net"] > r["rand_p95"] and d > 0)
    # secondary: cost filter
    tc = t[t.cost_r <= 0.10]
    rc = row(tc, "test")
    r["n_cost10"] = rc["n"]; r["net_cost10"] = rc["net"]; r["lo_cost10"] = rc["lo"]; r["hi_cost10"] = rc["hi"]
    tr_ = part(TR, "train")
    out.append(r)
tab = pd.DataFrame(out).set_index("name")
tab.to_csv(RES / "test_table.csv", float_format="%.4f")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(tab.round(3).to_string())

# breakdowns
def brk(t, by):
    return pd.DataFrame({k: row(g, "test") for k, g in t.groupby(by)}).T[["n", "per_day", "wr", "gross", "net", "lo", "hi", "pf"]]

bd = {}
for nm in [f"{sel['best_family']}: {picks[sel['best_family']]}", f"T6: {sel['T6_reversal_part']} else T5a", "T0 (3h)"]:
    t = sets[nm]
    for by in ("tf", "group"):
        b = brk(t, by); b.insert(0, "by", by); b.insert(0, "set", nm); bd[(nm, by)] = b
        print("\n", nm, "by", by); print(b.round(3).to_string())
pd.concat(bd.values()).to_csv(RES / "test_breakdown.csv", float_format="%.4f")
print("\nT6 sources:", t6.src.value_counts().to_dict(), t6.groupby("src").r_net.agg(["mean", "size"]).round(3).to_dict())

# filtering of fake signals vs T0 (3h): zones T0 lost vs won, kept by each pick
t0 = sets["T0 (3h)"].set_index("zid")
lost = set(t0.index[t0.r_net < 0]); won = set(t0.index[t0.why == "tp"])
fz = {}
for name, t in sets.items():
    if name.startswith("T0"):
        continue
    z = set(t.zid)
    fz[name] = dict(T0_losers_skipped=1 - len(z & lost) / len(lost), T0_winners_kept=len(z & won) / len(won),
                    zones_traded=len(z), zones_T0=len(t0))
fz = pd.DataFrame(fz).T
print("\n", fz.round(3).to_string()); fz.to_csv(RES / "test_filtering.csv", float_format="%.4f")
