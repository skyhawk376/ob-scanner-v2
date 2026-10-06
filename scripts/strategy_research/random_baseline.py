"""Simulator sanity check: random side, random minute in the window, market entry, SL 1 ATR(H1), TP 1R, 60 min.
Gross (cost_mult=0) should be ~0R; net shows the pure cost drag of the cost model."""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from common import OUT, TRAIN, TEST, asof, metrics, simulate, split, GROUP
from families import EU, US, window_bars, _req

rng = np.random.default_rng(7)
rows = []
for win, (a, b, basket) in {"EU": (480, 720, EU), "US": (870, 1080, US)}.items():
    for sym in basket:
        w = window_bars(sym, "Europe/Paris", a, b)
        days = w.groupby("date").head(1).index  # first bar per day
        for d0 in days:
            t = d0 + pd.Timedelta(minutes=int(rng.integers(0, b - a - 60)))
            rows.append(dict(sym=sym, t_sig=t, side=int(rng.choice([-1, 1])), win=win))
r = pd.DataFrame(rows)
parts = []
for sym, g in r.groupby("sym"):
    g = g.copy(); g["atr"] = asof(sym, "H1", g.t_sig, "atr"); parts.append(g)
r = pd.concat(parts).dropna()
c = asof  # noqa
req = pd.DataFrame([_req(sym=x.sym, t_active=x.t_sig, side=x.side, etype="market",
                         level=float(asof(x.sym, "M5", [x.t_sig], "close")[0]),
                         sl=float(asof(x.sym, "M5", [x.t_sig], "close")[0] - x.side * x.atr), tp_r=1.0, win=x.win)
                    for x in r.itertuples()])
# SL distance must be measured from the real fill: recompute SL from fill-agnostic level is fine (1 ATR from last close)
out = {}
for cm in (0.0, 1.0):
    tr = simulate(req, cost_mult=cm)
    a_, b_ = split(tr)
    out[f"cost{cm:g}"] = {"train": metrics(a_, TRAIN), "test": metrics(b_, TEST),
                          "by_group_train": {g: metrics(x, TRAIN)["avg"] for g, x in a_.groupby("group")}}
print(json.dumps(out, indent=1, default=float))
(OUT / "random_baseline.json").write_text(json.dumps(out, indent=1, default=float))
