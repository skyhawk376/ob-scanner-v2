#!/usr/bin/env python3
"""4 TEST example trades of T6 (reversal close-back, else sweep & reclaim): 2 wins, 2 losses -> /workspace/ob_shape/reversal_examples.png"""
import json
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from common_re import RES, C, part, compose_t6
from triggers import RULE, DUR

sel = json.loads((RES / "selection.json").read_text())
tr = part(pd.read_parquet(RES / "trades.parquet"), "test"); ev = part(pd.read_parquet(RES / "events.parquet"), "test")
t6 = compose_t6(ev, tr, sel["T6_reversal_part"])
t6 = t6[t6.tf.isin(["M15", "M30", "H1"]) & (t6.group != "CRYPTO") | t6.tf.isin(["M15", "M30", "H1"])]
rng = np.random.default_rng(3)
picks = []
for src, why, lab in (("rev", "tp", "WIN – reversal candle (close back above/below zone)"),
                      ("sweep", "tp", "WIN – no reversal, sweep & reclaim late entry"),
                      ("rev", "sl", "LOSS – reversal candle, then SL"),
                      ("sweep", "sl", "LOSS – sweep & reclaim, then SL")):
    c = t6[(t6.src == src) & (t6.why == why) & t6.tf.isin(["M15", "M30"]) & (t6.hold_real_min >= 45) & (t6.hold_real_min <= 150)]
    picks.append((c.iloc[int(rng.integers(len(c)))], lab))

fig, axs = plt.subplots(2, 2, figsize=(17, 11))
for ax, (x, lab) in zip(axs.ravel(), picks):
    tf = x.tf if x.src == "rev" else "M5"
    dur = pd.Timedelta(minutes=DUR[tf])
    b = C.resample(x.sym, RULE[tf])
    a0 = x.t0 - (14 if x.src == "rev" else 20) * dur; a1 = x.t_exit + 4 * dur
    b = b[(b.index >= a0) & (b.index <= a1)]
    xs = np.arange(len(b))
    for i, (ts, r) in enumerate(b.iterrows()):
        col = "#26a69a" if r.close >= r.open else "#ef5350"
        ax.vlines(i, r.low, r.high, color=col, lw=1)
        ax.add_patch(Rectangle((i - 0.35, min(r.open, r.close)), 0.7, max(abs(r.close - r.open), 1e-9), color=col))
    pos = lambda t: np.searchsorted(b.index, t, side="right") - 1
    ax.add_patch(Rectangle((-0.5, x.bot), len(b), x.top - x.bot, color="tab:blue", alpha=0.15, label=f"OB {x.tf} zone"))
    ax.axhline(x.entry, color="tab:blue", ls=":", lw=1, label="original OB entry (mid/open)")
    i0 = pos(x.t0); ax.axvline(i0, color="grey", ls="--", lw=0.8); ax.text(i0, ax.get_ylim()[1], " 1st touch", va="top", fontsize=8)
    if x.src == "rev":
        k = pos(x.t_trig - dur)
        ax.add_patch(Rectangle((k - 0.5, b.low.iloc[k]), 1, b.high.iloc[k] - b.low.iloc[k], fill=False, ec="purple", lw=2,
                               label="reversal candle (close back out of zone)"))
    else:
        ks = pos(x.t_sweep); ext = b.low.iloc[ks:pos(x.t_fill) + 1].min() if x.side > 0 else b.high.iloc[ks:pos(x.t_fill) + 1].max()
        ax.scatter([ks], [ext], marker="v" if x.side < 0 else "^", s=90, color="purple", zorder=5, label="sweep beyond distal")
    ref = x.entry_px if x.etype == "market" else x.level
    tp = ref + x.side * 2 * x.risk
    f, e = pos(x.t_fill), pos(x.t_exit)
    ax.hlines(x.entry_px, f, e, color="black", lw=2, label=f"entry {x.entry_px:.5g}")
    ax.hlines(x.sl, f, e, color="red", lw=2, label=f"SL {x.sl:.5g}")
    ax.hlines(tp, f, e, color="green", lw=2, label=f"TP +2R {tp:.5g}")
    ax.scatter([e], [x.exit_px], marker="x", s=80, color="black", zorder=6)
    ax.set_title(f"{lab}\n{x.sym} {x.tf} {'bull' if x.side > 0 else 'bear'} zone, {tf} candles, "
                 f"{x.t_fill.tz_convert('Europe/Paris'):%Y-%m-%d %H:%M} Paris → {x.why} {x.r_net:+.2f}R net", fontsize=10)
    step = max(1, len(b) // 8)
    ax.set_xticks(xs[::step]); ax.set_xticklabels([t.tz_convert("Europe/Paris").strftime("%m-%d %H:%M") for t in b.index[::step]], fontsize=7)
    ax.legend(fontsize=7, loc="best")
fig.suptitle("T6 = reversal close-back candle (T4, same TF) else sweep & reclaim (T5a) — TEST examples; SL zone distal / sweep extreme, TP +2R, 3h stop", fontsize=12)
fig.tight_layout()
fig.savefig("/workspace/ob_shape/reversal_examples.png", dpi=110)
fig.savefig(RES / "reversal_examples.png", dpi=110)
print([(p[0].sym, p[0].tf, p[0].src, p[0].why) for p in picks])
