#!/usr/bin/env python3
"""Visuals for the OB shape study (read-only; uses prod candle cache snapshot + results CSVs).

  /workspace/ob_shape/winners_vs_losers.png  real alerted prod zones, +2R (hold=tp) vs SL (hold=sl)
  /workspace/ob_shape/features.png           success rate by quintile of the most discussed shape features
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from scipy.stats import mannwhitneyu  # noqa: E402

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
OUT = Path("/workspace/ob_shape")
CACHE = Path("/workspace/ob_shape/prod/cache")
PARIS = "Europe/Paris"
BG, FG, GRID = "#0e1117", "#d0d4dc", "#2a2f3a"
UP, DN = "#26a69a", "#ef5350"
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "axes.edgecolor": GRID, "text.color": FG,
                     "axes.labelcolor": FG, "xtick.color": FG, "ytick.color": FG, "grid.color": GRID,
                     "font.size": 8})

WIN = [("XRP", "M5", "2026-10-08T00:35"), ("LINK", "M5", "2026-10-08T00:05"), ("NZDCAD", "M5", "2026-10-07T18:00"),
       ("BTC", "M5", "2026-10-07T16:05"), ("EURCAD", "M15", "2026-10-06T21:30"), ("NZDCHF", "H1", "2026-10-06T09:00")]
LOSE = [("XAUUSD", "M5", "2026-10-08T07:30"), ("CADJPY", "M15", "2026-10-08T07:15"), ("BTC", "M5", "2026-10-08T04:30"),
        ("GBPJPY", "M30", "2026-10-08T02:30"), ("NZDUSD", "M5", "2026-10-08T05:35"), ("AUDUSD", "H1", "2026-10-07T10:00")]


def pick(P, sym, tf, touch):
    m = P[(P.symbol == sym) & (P.tf == tf) & (P.alerted == 1) & P.touched_at.str.startswith(touch)]
    assert len(m) == 1, (sym, tf, touch, len(m))
    return m.iloc[0]


def draw(ax, z, ok):
    df = pd.read_parquet(CACHE / f"{z.symbol}_{z.tf}.parquet")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    t_ob, t_bos, t_touch = (pd.Timestamp(z[c]) for c in ("ts_ob", "ts_bos", "touched_at"))
    io, ib, it = (df.index.get_indexer([t])[0] for t in (t_ob, t_bos, t_touch))
    assert min(io, ib, it) >= 0, z.symbol
    bull = z.direction == "bull"
    # sanity: the OB candle is the zone
    assert abs(df.high.iloc[io] - z.high) <= 1e-6 * z.high and abs(df.low.iloc[io] - z.low) <= 1e-6 * z.low
    s = max(0, io - 12)
    gap = it - io
    e = min(len(df), it + 14)
    d = df.iloc[s:e]
    x = np.arange(len(d))
    w = 0.6
    for k, (o, h, l, c) in enumerate(d[["open", "high", "low", "close"]].to_numpy()):
        col = UP if c >= o else DN
        ax.vlines(k, l, h, color=col, lw=0.8)
        ax.add_patch(Rectangle((k - w / 2, min(o, c)), w, max(abs(c - o), 1e-12), color=col, lw=0))
    xo, xb, xt = io - s, ib - s, it - s
    # OB box from OB candle to the touch
    ax.add_patch(Rectangle((xo - 0.5, z.low), xt - xo + 1, z.high - z.low, fc=("#2e7dd1" if bull else "#d17a2e"),
                           alpha=0.25, ec=("#2e7dd1" if bull else "#d17a2e"), lw=1))
    ax.add_patch(Rectangle((xo - 0.5, df.low.iloc[io]), 1, df.high.iloc[io] - df.low.iloc[io], fill=False, ec="white", lw=1.2))
    # displacement candles OB+1..OB+2 outlined
    for j in (1, 2):
        if io + j < len(df) and io + j - s < len(d):
            r = df.iloc[io + j]
            ax.add_patch(Rectangle((xo + j - 0.5, r.low), 1, r.high - r.low, fill=False, ec="#ffd54f", lw=0.9, ls="--"))
    # FVG OB vs OB+2
    if io + 2 < len(df):
        a, b = (df.high.iloc[io], df.low.iloc[io + 2]) if bull else (df.high.iloc[io + 2], df.low.iloc[io])
        if b > a:
            ax.add_patch(Rectangle((xo + 0.5, a), min(8, len(d) - xo - 1), b - a, fc="#ab47bc", alpha=0.35, lw=0))
    # BOS
    if not np.isnan(z.piv_p):
        ax.hlines(z.piv_p, max(0, xb - 6), xb + 0.5, color="#90a4ae", lw=0.8, ls=":")
        ax.text(xb + 0.6, z.piv_p, "BOS", color="#90a4ae", fontsize=6, va="center")
    # levels from touch
    x1 = len(d) - 0.5
    for lvl, col, lab in ((z.entry, "#e0e0e0", "entry"), (z.sl, DN, "SL"), (z.tp2, UP, "TP 2R")):
        ax.hlines(lvl, xt - 0.5, x1, color=col, lw=1, ls="-" if lab == "entry" else "--")
        ax.text(x1, lvl, f" {lab}", color=col, fontsize=6, va="center")
    ax.axvline(xt, color="#78909c", lw=0.6, ls=":")
    lo_, hi_ = d.low.min(), d.high.max()
    lo_, hi_ = min(lo_, z.sl, z.tp2), max(hi_, z.sl, z.tp2)
    pad = (hi_ - lo_) * 0.06
    ax.set_ylim(lo_ - pad, hi_ + pad)
    ax.set_xlim(-1, len(d) + 3)
    tick = np.linspace(0, len(d) - 1, 4).astype(int)
    ax.set_xticks(tick)
    ax.set_xticklabels([d.index[i].tz_convert(PARIS).strftime("%d/%m %H:%M") for i in tick], fontsize=6)
    ax.tick_params(axis="y", labelsize=6)
    ax.grid(alpha=0.3)
    tp = t_touch.tz_convert(PARIS).strftime("%d/%m %H:%M")
    risk_bp = abs(z.entry - z.sl) / z.entry * 1e4
    res = "+2R (hold=tp)" if ok else "SL (hold=sl)"
    ax.set_title(f"{z.symbol} {z.tf} {'ACHAT' if bull else 'VENTE'} {int(z.score)}★ — touch {tp} Paris\n"
                 f"{res} · scanner: {z.status} · trade_sim: {z.trade_exit} · textbook fails {int(z.tb_fails)}"
                 f" · risk {risk_bp:.1f} bp" + (f" · gap {gap} bars" if gap > 40 else ""),
                 fontsize=7, color=UP if ok else DN)


def winners_vs_losers(P):
    fig, axes = plt.subplots(4, 3, figsize=(17, 16))
    for ax, key in zip(axes.flat[:6], WIN):
        draw(ax, pick(P, *key), True)
    for ax, key in zip(axes.flat[6:], LOSE):
        draw(ax, pick(P, *key), False)
    fig.suptitle("Zones OB réellement alertées (prod, 06–08/10/2026) — haut: +2R atteint avant SL · bas: SL\n"
                 "box = zone OB · contour blanc = bougie OB · pointillés jaunes = displacement (OB+1..2) · violet = FVG ·"
                 " lignes = entrée / SL / TP 2R depuis le toucher", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    fig.savefig(OUT / "winners_vs_losers.png", dpi=110)
    plt.close(fig)


def rate_ci(y):
    n = len(y)
    p = y.mean() if n else np.nan
    se = np.sqrt(p * (1 - p) / n) if n else np.nan
    return p, 1.96 * se, n


def features(H, P):
    feats = [("fvg_atr", "FVG size (ATR)"), ("impulse3_atr", "Impulse 3 bars after OB (ATR)"),
             ("approach_speed", "Approach speed to the zone (ATR/bar)"), ("tb_fails", "Textbook criteria failed (T1–T8)")]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, (f, lab) in zip(axes.flat, feats):
        for k, (name, d, col, off) in enumerate((("history 2023–26", H, "#64b5f6", -0.18), ("prod", P, "#ffb74d", 0.18))):
            d = d[d.hold.isin(["tp", "sl"])].dropna(subset=[f])
            y = (d.hold == "tp").astype(float)
            if f == "tb_fails":
                b = d[f].clip(upper=4).astype(int)
                cats = list(range(5))
                names = ["0", "1", "2", "3", "≥4"]
            else:
                b = pd.qcut(d[f], 5, labels=False, duplicates="drop")
                cats = sorted(b.unique())
                names = [f"Q{i + 1}" for i in cats]
            ps = [rate_ci(y[b == c]) for c in cats]
            xs = np.arange(len(cats)) + off
            ax.bar(xs, [p for p, _, _ in ps], width=0.34, color=col, alpha=0.8,
                   yerr=[e for _, e, _ in ps], ecolor=FG, capsize=2, label=None)
            for xx, (p, e, n) in zip(xs, ps):
                ax.text(xx, 0.02, f"n={n}", rotation=90, fontsize=6, ha="center", va="bottom", color=BG)
            a, c0 = d[f][y == 1], d[f][y == 0]
            auc = mannwhitneyu(a, c0).statistic / (len(a) * len(c0))
            ax.plot([], [], color=col, lw=6,
                    label=f"{name}: median win {a.median():.2f} vs loss {c0.median():.2f} · AUC {auc:.3f} (n={len(d)})")
        ax.axhline(1 / 3, color=DN, ls="--", lw=0.8)
        ax.text(-0.45, 1 / 3 + 0.01, "breakeven 2R (33%)", color=DN, fontsize=6)
        ax.set_xticks(np.arange(len(names)))
        ax.set_xticklabels(names)
        ax.set_ylim(0, 0.8)
        ax.set_title(lab + (" — quintiles" if f != "tb_fails" else ""), fontsize=9)
        ax.set_ylabel("share +2R before SL (95% CI)")
        ax.legend(fontsize=6.5, loc="upper right", facecolor=BG, edgecolor=GRID)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("OB shape: success (+2R before SL, limit at entry) by feature bucket — history (scanner-parity, "
                 "14 symbols, M5–H4) vs prod touched zones (all TFs)\nAUC 0.5 = no separation; history AUCs all within "
                 "0.49–0.51 → shape does not predict the outcome", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "features.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    P = pd.read_csv(RES / "prod_zones.csv")
    H = pd.read_parquet(RES / "hist_zones.parquet")
    winners_vs_losers(P)
    features(H, P)
    print("ok")
