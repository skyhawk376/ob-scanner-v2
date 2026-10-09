#!/usr/bin/env python3
"""TRAIN-only: per-config metrics + pre-registered selection (writes results/selection.json). Does not read TEST."""
import json
import pandas as pd
from common_re import RES, FAMS, MIN_N, part, row, compose_t6

tr = part(pd.read_parquet(RES / "trades.parquet"), "train")
ev = part(pd.read_parquet(RES / "events.parquet"), "train")
tab = pd.DataFrame({cfg: row(g, "train") for cfg, g in tr.groupby("cfg")}).T
tab["fam"] = [c.split("|")[0].replace("T5a", "T5").replace("T5b", "T5") for c in tab.index]
tab.to_csv(RES / "train_grid.csv", float_format="%.4f")
sel = {}
for f in FAMS:
    g = tab[tab.fam == f]
    ok = g[g.n >= MIN_N]
    sel[f] = (ok.net.idxmax() if len(ok) else g.n.idxmax())
rev_best = max(["T1", "T2", "T4"], key=lambda f: tab.loc[sel[f], "net"])
sel["T6_reversal_part"] = sel[rev_best]
sel["best_family"] = max(FAMS, key=lambda f: tab.loc[sel[f], "net"])
t6 = compose_t6(ev, tr, sel[rev_best])
t6r = row(t6, "train")
pd.set_option("display.width", 220)
print(tab.sort_index().round(3).to_string())
print("selection:", json.dumps(sel, indent=1))
print("T6 TRAIN:", {k: round(v, 3) for k, v in t6r.items()}, t6.src.value_counts().to_dict())
(RES / "selection.json").write_text(json.dumps(sel, indent=1))
