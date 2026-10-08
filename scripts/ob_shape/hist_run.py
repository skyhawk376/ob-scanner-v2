#!/usr/bin/env python3
"""Historical Filtre B zones (scanner-parity Pine port) + shape features + outcomes.

Data: research M1 (HistData FX/metals, Binance crypto), 2023-01 → 2026-09-30, 14 symbols of the
Filtre B groups (METAUX/FOREX/CRYPTO) resampled to M5/M15/M30/H1/H4 (UTC bins).
Engine: tradingview/pine_reference.PineEngine (causal bar-by-bar port, parity-checked vs detect.py).
Listed = score at alert time >= 4 (★5 pending on H4), ★1 FVG; kept if touched.
Outcomes:
  life      : scanner lifecycle status (reaction = +2R before SL from first contact, no fill needed)
  hold      : TF bars, limit at entry must fill, then +2R vs SL first (no time limit) -> tp|sl
  r_net/... : realistic live sim on M1 (prod trade_sim rules: limit at entry from the touch bar,
              fill within 25h, TP 2R / SL / 1h time stop) with the per-asset cost model of
              scripts/strategy_research/common.py (r_gross = same at zero cost).
Output: scripts/ob_shape/results/hist_zones.parquet
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tradingview"))
sys.path.insert(0, str(ROOT / "scripts" / "strategy_research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as C  # noqa: E402
from features import compute_features, fill_outcome, strict_pivots, textbook_flags  # noqa: E402
from pine_reference import (ST_ACTIVE, ST_FAIL, ST_REACTION, ST_TOUCHED, STATUS_NAME,  # noqa: E402
                            PineEngine, epoch_seconds)

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
SYMS = [s for s, g in C.GROUP.items() if g in ("METALS", "FOREX", "CRYPTO")]
TFS = {"M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}
START = pd.Timestamp("2023-01-02", tz="UTC")


class Eng(PineEngine):
    """Same algorithm; records the broken pivot and prunes finished zones (speed only)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.done = []

    def _new_zone(self, bull, ob, j, k):
        z = super()._new_zone(bull, ob, j, k)
        piv = self.ph if bull else self.pl
        z.piv_i, z.piv_p = piv[-1]
        return z

    def step(self):
        super().step()
        keep = []
        for z in self.zones:
            (keep if z.status in (ST_ACTIVE, ST_TOUCHED) else self.done).append(z)
        self.zones = keep

    def all_listed(self, min_score=4):
        return [z for z in self.done + self.view() if z.score_pre() >= min_score]


def run(sym: str, tf: str) -> pd.DataFrame:
    df = C.resample(sym, TFS[tf])
    df = df[df.high >= df.low]
    t = epoch_seconds(df.index)
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    eng = Eng(o, h, l, c, t, tf)
    eng.run_to(len(df) - 1)
    N = eng.N
    ph, pl = strict_pivots(h, l, N)
    rows = []
    for z in eng.all_listed(4):
        if not z.s1 or z.touch < 0 or z.status not in (ST_TOUCHED, ST_REACTION, ST_FAIL):
            continue
        if df.index[z.ob] < START:
            continue
        piv_opp = pl if z.bull else ph
        f = compute_features(o, h, l, c, t, ob=z.ob, j=z.bos, k=z.leg, piv_i=z.piv_i, piv_p=z.piv_p,
                             touch=z.touch, bull=z.bull, top=z.top, bot=z.bot, entry=z.entry, sl=z.sl,
                             atr=z.atr, pivots_opp=piv_opp, N=N)
        hold, hold_bars, mfe = fill_outcome(o, h, l, c, touch=z.touch, bull=z.bull, entry=z.entry, sl=z.sl)
        s5 = z.s5_touch if z.pending else z.s5
        rows.append(dict(sym=sym, group=C.GROUP[sym], tf=tf, direction="bull" if z.bull else "bear",
                         ts_ob=df.index[z.ob], ts_bos=df.index[z.bos], ts_touch=df.index[z.touch],
                         ob_i=z.ob, bos_i=z.bos, leg_i=z.leg, touch_i=z.touch, piv_i=z.piv_i, piv_p=z.piv_p,
                         top=z.top, bot=z.bot, entry=z.entry, sl=z.sl, tp=z.tp, atr=z.atr,
                         s1=int(z.s1), s2=int(z.s2), s3=int(z.s3()), s4=int(z.s4), s5=int(s5),
                         score=z.score(), score_pre=z.score_pre(), life=STATUS_NAME[z.status],
                         hold=hold, hold_bars=hold_bars, **f, **textbook_flags(f)))
    return pd.DataFrame(rows)


def job(arg):
    sym, tf = arg
    t0 = time.time()
    try:
        d = run(sym, tf)
    except Exception as e:  # pragma: no cover
        print("ERR", sym, tf, e, flush=True)
        return pd.DataFrame()
    print(f"{sym} {tf}: {len(d)} touched zones ({time.time() - t0:.0f}s)", flush=True)
    return d


def add_sim(d: pd.DataFrame) -> pd.DataFrame:
    req = pd.DataFrame(dict(sym=d.sym, t_active=d.ts_touch, side=np.where(d.direction == "bull", 1, -1),
                            etype="limit", level=d.entry, sl=d.sl, tp_r=2.0, expiry_min=25 * 60,
                            hold_min=60, zid=d.index))
    out = d.copy()
    for mult, col in ((1.0, "net"), (0.0, "gross")):
        r = C.simulate(req.copy(), cost_mult=mult).set_index("zid")
        out[f"r_{col}"] = r["r_net"]
        if col == "net":
            out["sim_exit"] = r["why"]
            out["t_fill"] = r["t_fill"]
            out["cost_r"] = r["comm"] / r["risk"]
    out["sim_exit"] = out["sim_exit"].fillna("nofill")
    # H4 / D1 EMA50 bias at the touch (last closed bar), like trend_bias.py
    for sym, g in out.groupby("sym"):
        sgn = np.where(g.direction == "bull", 1, -1)
        b4 = C.trend(sym, "H4", g.ts_touch, "ema50")
        bd = C.trend(sym, "D1", g.ts_touch, "ema50")
        out.loc[g.index, "bias_h4_ok"] = (b4 == sgn).astype(int)
        out.loc[g.index, "bias_d1_ok"] = (bd == sgn).astype(int)
        out.loc[g.index, "aligned_h4d1"] = ((b4 == sgn) & (bd == sgn)).astype(int)
    return out


if __name__ == "__main__":
    tfs = sys.argv[1].split(",") if len(sys.argv) > 1 else list(TFS)
    jobs = [(s, tf) for tf in tfs for s in SYMS]
    with ProcessPoolExecutor(6) as ex:
        parts = list(ex.map(job, jobs))
    d = pd.concat([p for p in parts if len(p)], ignore_index=True)
    d = add_sim(d)
    d.to_parquet(OUT / "hist_zones.parquet")
    print(len(d), "zones saved")
    print(d.groupby("tf").agg(n=("sym", "size"), life_react=("life", lambda s: (s == "reaction").mean()),
                              hold_tp=("hold", lambda s: (s == "tp").mean()), r_net=("r_net", "mean")))
