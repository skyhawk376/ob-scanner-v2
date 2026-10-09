"""XAU clean-OB study (PREREG_XAU_M5_CLEAN.md). `train` -> grid + selection.json; `test` -> selected cells, CSVs."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wr70"))
from sim import EVENTS, ZONES, C, part, run, row, simulate  # noqa: E402

STAGE = sys.argv[1]; RES = Path(__file__).resolve().parent / "results"
Z = pd.read_parquet(ZONES)
TFS = ["M5", "M15", "M30", "H1"]
x = Z[(Z.sym == "XAUUSD") & Z.tf.isin(TFS)]
Q = {"base": pd.Series(True, index=x.index), "Q1": x.tb_fails <= 1, "Q2": x.tb_fails == 0,
     "Q3": (x.disp_maxbody_atr >= 1.5) & (x.fvg_atr >= 0.5) & (x.ob_body_ratio >= 0.5),
     "Q4": (x.T6_not_chop == 1) & (x.T3_bos_fast == 1) & (x.T4_bos_margin == 1) & (x.sweep_leg == 1)}
Q["Q5"] = Q["Q3"] & Q["Q4"]
EV = part(pd.read_parquet(EVENTS), STAGE); EV = EV[EV.zid.isin(x.index)]
CFG = [(e, tp, h) for e in ("E1", "E2", "E3") for tp in (0.3, 0.5, 1.0, 2.0) for h in ("1h", "3h")]
T = {c: run(EV, Z, c[0], c[2], c[1], 0.0) for c in CFG}
def cell(t, tf, q):
    return t[(t.tf == tf) & t.zid.isin(x.index[Q[q] & (x.tf == tf)])]
def name(c): return f"{c[0]}|tp{c[1]}|{c[2]}"
if STAGE == "train":
    rows = []
    for tf in TFS:
        for q in Q:
            for c in CFG:
                r = row(cell(T[c], tf, q), "train"); r.update(tf=tf, q=q, cfg=name(c)); rows.append(r)
    G = pd.DataFrame(rows); G.to_csv(RES / "train_grid.csv", index=False, float_format="%.4f")
    sel = {}
    for (tf, q), g in G.groupby(["tf", "q"], sort=False):
        el = g[(g.wr >= 0.72) & (g.n >= 20)].sort_values("net", ascending=False)
        fb = g[g.n >= 20].sort_values("wr", ascending=False)
        pick = el if len(el) else fb
        sel[f"{tf}|{q}"] = dict(cfg=pick.cfg.iloc[0] if len(pick) else None, eligible=bool(len(el)),
                                train_n=int(pick.n.iloc[0]) if len(pick) else int(g.n.max()),
                                train_wr=float(pick.wr.iloc[0]) if len(pick) else None,
                                train_net=float(pick.net.iloc[0]) if len(pick) else None)
    (RES / "selection.json").write_text(json.dumps(sel, indent=1)); print(json.dumps(sel, indent=1))
else:
    sel = json.loads((RES / "selection.json").read_text()); rng = np.random.default_rng(5)
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
    rows, trades = [], {}
    split = pd.Timestamp("2025-07-01", tz="UTC")
    for k, s in sel.items():
        tf, q = k.split("|")
        nz = int(((x.tf == tf) & Q[q] & (pd.to_datetime(x.ts_touch, utc=True) >= split)).sum())
        r = dict(tf=tf, q=q, cfg=s["cfg"], zones_test=nz, eligible=s["eligible"], train_n=s["train_n"],
                 train_wr=s["train_wr"], train_net=s["train_net"])
        if s["cfg"]:
            e, tp, h = s["cfg"].split("|"); c = (e, float(tp[2:]), h)
            t = cell(T[c], tf, q); trades[k] = t
            r.update(row(t, "test")); r["rand_mean"], r["rand_p95"] = rand(t, c[1], h)
        rows.append(r)
    R = pd.DataFrame(rows); R["wr70"] = R.wr >= 0.70; R["profitable"] = R.lo > 0
    R.to_csv(RES / "test_table.csv", index=False, float_format="%.4f")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(R.round(3).to_string(index=False))
    for tf in TFS:
        g = R[(R.tf == tf) & (R.n >= 10)]
        if not len(g): print(tf, "no cell with >=10 TEST trades"); continue
        b = g.sort_values("net", ascending=False).iloc[0]; k = f"{tf}|{b.q}"
        zs = x[(x.tf == tf) & Q[b.q] & (pd.to_datetime(x.ts_touch, utc=True) >= split)]
        t = trades[k].set_index("zid")
        out = pd.DataFrame(dict(
            touch_paris=pd.to_datetime(zs.ts_touch, utc=True).dt.tz_convert("Europe/Paris").dt.strftime("%Y-%m-%d %H:%M"),
            direction=zs.direction, zone_top=zs.top, zone_bot=zs.bot, zone_size_usd=(zs.top - zs.bot).round(2),
            entry=zs.entry, sl=zs.sl, tb_fails=zs.tb_fails))
        out["config"] = b.cfg
        out["outcome"] = [t.loc[i, "why"] if i in t.index else "no trade" for i in zs.index]
        out["r_net"] = [round(float(t.loc[i, "r_net"]), 3) if i in t.index else np.nan for i in zs.index]
        out.to_csv(RES / f"test_zones_{tf}_{b.q}.csv", index_label="zid")
        print(tf, "best", k, b.cfg, int(b.n), round(b.net, 3))
