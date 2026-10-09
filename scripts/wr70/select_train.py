"""TRAIN grid (stage A 60 + stage B ≤15) and pre-registered selection -> results/train_grid.csv, selection.json."""
import json
import pandas as pd
from sim import EVENTS, ZONES, RES, TPS, FILTERS, part, run, apply_filter, row

EV = part(pd.read_parquet(EVENTS), "train"); Z = pd.read_parquet(ZONES)
cache = {}
def trades(entry, hold, tp, be):
    k = (entry, hold, tp, be)
    if k not in cache:
        cache[k] = run(EV, Z, entry, hold, tp, be)
    return cache[k]

def evaluate(entry, hold, tp, be, filt, stage):
    t = apply_filter(trades(entry, hold, tp, be), filt)
    r = row(t, "train")
    r.update(cfg=f"{entry}|tp{tp}|{hold}|be{int(be > 0)}|{filt}", entry=entry, tp=tp, hold=hold, be=int(be > 0),
             filt=filt, stage=stage)
    return r

rows = [evaluate(e, "1h", tp, 0.0, f, "A") for e in ("E1", "E2", "E3") for tp in TPS for f in FILTERS]
A = pd.DataFrame(rows)
def rank(df):
    el = df[(df.wr >= 0.72) & (df.n >= 300)].sort_values("net", ascending=False)
    rest = df[(df.n >= 300) & ~df.index.isin(el.index)].sort_values("wr", ascending=False)
    return el, rest
el, rest = rank(A)
top5 = pd.concat([el, rest]).head(5)
for _, r in top5.iterrows():
    for hold, be in (("3h", 0.0), ("1h", 0.5), ("3h", 0.5)):
        rows.append(evaluate(r.entry, hold, r.tp, be, r.filt, "B"))
G = pd.DataFrame(rows).drop_duplicates("cfg")
G.to_csv(RES / "train_grid.csv", index=False, float_format="%.4f")
el, rest = rank(G)
sel = dict(selected=el.cfg.iloc[0] if len(el) else rest.cfg.iloc[0], eligible=bool(len(el)),
           top5=(list(el.cfg.head(5)) + list(rest.cfg))[:5] if len(el) else list(rest.cfg.head(5)),
           n_configs=len(G), n_eligible=len(el))
(RES / "selection.json").write_text(json.dumps(sel, indent=1))
pd.set_option("display.width", 250)
print(G.sort_values(["wr"], ascending=False).round(3).to_string(index=False))
print(json.dumps(sel, indent=1))
