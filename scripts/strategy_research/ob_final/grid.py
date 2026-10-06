"""Aggregate per-asset trades into the pre-registered grids, select on TRAIN, read TEST.
Usage: python grid.py            -> grid_*.csv, selection.json
"""
from __future__ import annotations
import json, itertools, sys
import numpy as np, pandas as pd
import core as C

TR_DIR = C.CACHE / "trades"
TRAIN0 = pd.Timestamp("2015-05-01", tz="UTC")
WK_TRAIN = C.weeks(TRAIN0, C.SPLIT); WK_TEST = C.weeks(C.SPLIT, C.END); WK_RECENT = C.weeks(C.RECENT, C.END)
SPLIT_NS, RECENT_NS = C.SPLIT.value, C.RECENT.value

def load(cost=None, mgmt=None, fam=None, holds=None):
    parts = []
    for p in sorted(TR_DIR.glob("*.parquet")):
        d = pd.read_parquet(p)
        if cost is not None: d = d[d.cost.isin(cost if isinstance(cost, (list, tuple)) else [cost])]
        if mgmt is not None: d = d[d.mgmt.isin(mgmt if isinstance(mgmt, (list, tuple)) else [mgmt])]
        if fam is not None: d = d[d.fam == fam]
        if holds is not None: d = d[d.hold.isin(holds)]
        for c in ("sym", "tf", "entry", "tp", "hold", "fam"): d[c] = d[c].astype(str)
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["period"] = np.where(d.t_fill < SPLIT_NS, "train", "test")
    d["group"] = d.sym.map(C.GROUP)
    return d

# ---- family config spaces (prereg §4)
def masks_zone(d: pd.DataFrame, trends=("none", "tr50")):
    out = {}
    for df_, st, tr in itertools.product(("BOS", "FVG"), ("any", "s3"), trends):
        m = np.ones(len(d), bool)
        if df_ == "FVG": m &= d.fvg.to_numpy()
        if st == "s3": m &= (d.score4 >= 3).to_numpy()
        if tr != "none": m &= (d[tr].to_numpy() == d.side.to_numpy())
        out[(df_, st, tr)] = m
    return out

def masks_ltf(d):
    out = {}
    for st, tr in itertools.product(("any", "s3"), ("none", "tr50")):
        m = np.ones(len(d), bool)
        if st == "s3": m &= (d.score4 >= 3).to_numpy()
        if tr != "none": m &= (d[tr].to_numpy() == d.side.to_numpy())
        out[(st, tr)] = m
    return out

def stats(g: pd.DataFrame) -> pd.Series:
    tr = g[g.period == "train"]; te = g[g.period == "test"]
    out = {}
    for nm, x, wk in (("train", tr, WK_TRAIN), ("test", te, WK_TEST)):
        r = x.sort_values("t_fill").r_net.to_numpy(float)
        m = C.metrics(r, wk)
        for k in ("n", "per_wk", "wr", "avg", "lo", "hi", "t", "pf", "maxdd", "streak"): out[f"{nm}_{k}"] = m[k]
    return pd.Series(out)

def grid_family(fam: str, d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if fam in ("A", "C", "EA", "EC"):
        z = d[d.fam == "Z"]
        if fam in ("A", "EA"):
            z = z[z.tf.isin(["H4", "D1"])]; trends = ("none", "tr50"); holds = ("5d", "10d") if fam == "A" else ("3h",)
        else:
            z = z[z.sym.isin(C.INDICES) & z.tf.isin(["H1", "H4"])]; trends = ("tr20", "tr50"); holds = ("1d", "2d") if fam == "C" else ("3h",)
        z = z[z.hold.isin(holds)]
        for key, m in masks_zone(z, trends).items():
            zz = z[m]
            for (tf, en, tp, ho), g in zz.groupby(["tf", "entry", "tp", "hold"]):
                s = stats(g); s["cfg"] = f"{fam}|{tf}|{key[0]}|{key[1]}|{key[2]}|{en}|{tp}|{ho}"
                s["tf"], s["def"], s["stars"], s["trend"], s["entry"], s["tp"], s["hold"] = tf, *key, en, tp, ho
                rows.append(s)
    else:  # B / EB
        z = d[d.fam == "B"]; holds = ("2d",) if fam == "B" else ("3h",)
        z = z[z.hold.isin(holds)]
        for key, m in masks_ltf(z).items():
            zz = z[m]
            for (tf, en, tp, ho), g in zz.groupby(["tf", "entry", "tp", "hold"]):
                s = stats(g); s["cfg"] = f"{fam}|{tf}|{key[0]}|{key[1]}|{en}|{tp}|{ho}"
                s["tf"], s["stars"], s["trend"], s["entry"], s["tp"], s["hold"] = tf, *key, en, tp, ho
                rows.append(s)
    return pd.DataFrame(rows)

def cfg_mask(d: pd.DataFrame, cfg: str) -> np.ndarray:
    p = cfg.split("|"); fam = p[0]
    if fam in ("A", "C", "EA", "EC"):
        _, tf, df_, st, tr, en, tp, ho = p
        m = (d.fam == "Z") & (d.tf == tf) & (d.entry == en) & (d.tp == tp) & (d.hold == ho)
        if fam in ("C", "EC"): m &= d.sym.isin(C.INDICES)
        if df_ == "FVG": m &= d.fvg
    else:
        _, tf, st, tr, en, tp, ho = p
        m = (d.fam == "B") & (d.tf == tf) & (d.entry == en) & (d.tp == tp) & (d.hold == ho)
    if st == "s3": m &= d.score4 >= 3
    if tr != "none": m &= d[tr] == d.side
    return m.to_numpy()

def select(g: pd.DataFrame):
    el = g[(g.train_n >= 100) & (g.train_per_wk >= 0.25)]
    flag = "n>=100"
    if el.empty:
        el = g[g.train_n >= 50]; flag = "fallback n>=50"
    if el.empty: return None, flag
    return el.sort_values("train_t", ascending=False).iloc[0], flag

if __name__ == "__main__":
    fams = sys.argv[1:] or ["A", "B", "C"]
    d = load(cost=1.0, mgmt=0)
    d0 = load(cost=0.0, mgmt=0)
    sel = {}
    sel_path = C.OUT / "selection.json"
    if sel_path.exists(): sel = json.loads(sel_path.read_text())
    for fam in fams:
        g = grid_family(fam, d)
        g0 = grid_family(fam, d0)[["cfg", "train_avg", "test_avg"]].rename(columns={"train_avg": "train_gross", "test_avg": "test_gross"})
        g = g.merge(g0, on="cfg", how="left")
        g.to_csv(C.OUT / f"grid_{fam}.csv", index=False)
        w, flag = select(g)
        sel[fam] = dict(winner=None if w is None else w["cfg"], flag=flag, K=len(g),
                        n_train_pos=int((g.train_avg > 0).sum()), n_test_pos=int((g.test_avg > 0).sum()),
                        n_eligible=int(((g.train_n >= 100) & (g.train_per_wk >= 0.25)).sum()),
                        best_train_t=float(g.train_t.max()))
        print(fam, json.dumps(sel[fam]), flush=True)
        if w is not None:
            print(w[["train_n", "train_per_wk", "train_avg", "train_t", "train_gross", "test_n", "test_avg", "test_lo", "test_hi", "test_gross"]].to_string())
    sel_path.write_text(json.dumps(sel, indent=1))
