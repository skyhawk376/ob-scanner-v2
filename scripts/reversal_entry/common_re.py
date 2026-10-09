"""Shared helpers: split, metrics table, T6 composition."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "strategy_research"))
import common as C  # noqa: E402

RES = HERE / "results"
SPLIT = C.SPLIT
PERIOD = {"train": C.TRAIN, "test": C.TEST}
FAMS = ["T1", "T2", "T3", "T4", "T5"]
MIN_N = 300


def part(df, which):
    t = pd.DatetimeIndex(df.t0)
    return df[t < SPLIT] if which == "train" else df[t >= SPLIT]


def row(tr, which):
    m = C.metrics(tr, PERIOD[which], "r_net")
    g = tr.r_gross.mean() if len(tr) else np.nan
    return dict(n=m["n"], per_day=m["per_wd"], wr=m["wr"], gross=g, net=m["avg"], lo=m["lo"], hi=m["hi"],
                pf=m["pf"], maxdd=m["maxdd"], hold_min=tr.hold_real_min.mean() if len(tr) else np.nan)


def compose_t6(ev, tr, rev_cfg):
    """Per zone: reversal event of rev_cfg vs T5a event (same hold): earlier t_active wins; one trade max."""
    reg = rev_cfg.split("|")[-1]
    a = ev[ev.cfg == rev_cfg][["zid", "t_active"]].assign(src="rev", cfg_src=rev_cfg)
    b = ev[ev.cfg == f"T5a|m1|sweep|{reg}"][["zid", "t_active"]].assign(src="sweep", cfg_src=f"T5a|m1|sweep|{reg}")
    both = pd.concat([a, b]).sort_values(["zid", "t_active"]).drop_duplicates("zid", keep="first")
    key = both.set_index(["zid", "cfg_src"]).index
    t = tr.set_index(["zid", "cfg"])
    out = t[t.index.isin(key)].reset_index()
    out["src"] = np.where(out.cfg == rev_cfg, "rev", "sweep")
    out["cfg"] = f"T6|{rev_cfg}+T5a"
    return out
