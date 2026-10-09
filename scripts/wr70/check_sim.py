"""Check: BE off reproduces common.simulate on TRAIN orders (no outcome inspection beyond equality)."""
import numpy as np, pandas as pd
from sim import C, EVENTS, part, build_orders, simulate
EV = part(pd.read_parquet(EVENTS), "train")
for ent in ("E1", "E2", "E3"):
    e = build_orders(EV, ent, "1h", 0.5, 0.0)
    a = simulate(e, 1.0).set_index("rid").sort_index(); b = C.simulate(e, 1.0).set_index("rid").sort_index()
    assert a.index.equals(b.index), ent
    print(ent, len(a), "max |dR| =", float(np.nanmax(np.abs(a.r_net - b.r_net))))
