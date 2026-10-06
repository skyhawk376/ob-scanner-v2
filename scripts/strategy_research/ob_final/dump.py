"""Dump trades of the frozen winners + data inventory (for the report)."""
import json
import numpy as np, pandas as pd
import core as C
from grid import load, cfg_mask

sel = json.loads((C.OUT / "selection.json").read_text())
D = load(cost=1.0, mgmt=0)
for fam in ("A", "B", "C", "EA"):
    x = D[cfg_mask(D, sel[fam]["winner"])].sort_values("t_fill").copy()
    for c in ("t_fill", "t_exit"): x[c] = pd.to_datetime(x[c], utc=True).dt.tz_convert("Europe/Paris")
    x.drop(columns=["period"]).to_csv(C.OUT / f"trades_winner_{fam}.csv", index=False)
inv = []
for s in C.ASSETS:
    df = C.load_m1(s)
    gaps = (df.index.to_series().diff() > pd.Timedelta(hours=3)).sum()
    inv.append(dict(sym=s, group=C.GROUP[s], first=str(df.index[0]), last=str(df.index[-1]), m1_rows=len(df), gaps_gt3h=int(gaps),
                    zones=len(pd.read_parquet(C.CACHE / f"zones_{s}.parquet"))))
pd.DataFrame(inv).to_csv(C.OUT / "data_inventory.csv", index=False)
print(pd.DataFrame(inv).to_string())
