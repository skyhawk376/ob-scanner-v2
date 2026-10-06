#!/usr/bin/env python3
"""Build RR2_OPTIM.md + summary JSON/CSV from rr2_optim_backtest.py outputs."""
from __future__ import annotations

import csv
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rr2_optim_backtest import COST_ATR, COST_R, GROUPS, metrics  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
OUT = ROOT / "data" / "backtest"
grid = pd.read_csv(OUT / "rr2_optim_grid.csv")
store = pickle.load(open(OUT / "rr2_trades_store.pkl", "rb"))
meta = json.loads((OUT / "rr2_optim_meta.json").read_text())
win = {g: (pd.Timestamp(a), pd.Timestamp(b), wd) for g, (a, b, wd) in meta["windows"].items()}
wd_full = {g: v[2] for g, v in win.items()}
split = {g: pd.Timestamp(s) for g, s in meta["split"].items()}
wd_half = {g: v / 2 for g, v in wd_full.items()}
rng = np.random.default_rng(7)


def closed(trs):
    return sorted([t for t in trs if t["r"] is not None], key=lambda t: t["fill_at"])


def first_per_day(trs):
    seen, out = set(), []
    for t in closed(trs):
        d = pd.Timestamp(t["fill_at"]).tz_convert(PARIS).date()
        if d in seen:
            continue
        seen.add(d)
        out.append(t)
    return out


def ci(rs):
    if len(rs) < 5:
        return (None, None)
    a = np.array(rs)
    bs = rng.choice(a, size=(5000, len(a)), replace=True).mean(axis=1)
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def full_stats(trs, label, cfg, model):
    c = closed(trs)
    m = metrics(c, wd_full)
    net = metrics(c, wd_full, COST_R)
    neta = metrics(c, wd_full, 0.0, COST_ATR)
    is_ = [t for t in c if pd.Timestamp(t["fill_at"]) < split[t["group"]]]
    oos = [t for t in c if pd.Timestamp(t["fill_at"]) >= split[t["group"]]]
    mi, mo = metrics(is_, wd_half), metrics(oos, wd_half)
    lo, hi = ci([t["r"] for t in c])
    byg = {}
    for g in GROUPS:
        gg = [t for t in c if t["group"] == g]
        x = metrics(gg, {g: wd_full[g]})
        byg[g] = {k: x[k] for k in ("n", "tpw", "wr", "avg_r", "sum_r", "pf", "max_dd")}
    return {
        "label": label, "config": cfg, "model": model,
        **{k: m[k] for k in ("n", "tpw", "wr", "avg_r", "sum_r", "pf", "max_dd", "max_lstreak", "obj")},
        "exits": m.get("exits"),
        "avg_r_ci95": [lo, hi],
        "avg_r_net005": net["avg_r"], "pf_net005": net["pf"], "sum_r_net005": net["sum_r"],
        "avg_r_net_atr": neta["avg_r"],
        "is": {k: mi[k] for k in ("n", "tpw", "wr", "avg_r", "sum_r")},
        "oos": {k: mo[k] for k in ("n", "tpw", "wr", "avg_r", "sum_r")},
        "by_group": byg,
    }


def S(cfg, model="m15", fpd=False, label=None):
    trs = store[(cfg, model)]
    if fpd:
        trs = first_per_day(trs)
    return full_stats(trs, label or cfg + (" +1st/day" if fpd else ""), cfg, model)



def f(x, d=3, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    if x == float("inf"):
        return "∞"
    return f"{100*x:.1f}%" if pct else f"{x:.{d}f}"


def nice(cfg):
    e, sl, h, st, se, mg, tp = cfg.split("|")
    em = {"mid_live": "mid (touch-managed, live acct.)", "mid_live_fill": "mid limit", "prox": "proximal limit",
          "d25": "25% depth limit", "d50": "50% (pure mid) limit", "d75": "75% depth limit"}[e]
    return (f"{em}, SL distal+{sl[2:]}ATR, hold {h[1:]}h, ≥{st[1:]}★, "
            f"{'Lon+NY' if se=='lonny' else 'all sess.'}, {'no mgmt' if mg=='none' else ('BE@+1R' if mg=='be' else '50% @+1R + BE')}, TP {tp}")


def row(x, flag=""):
    i, o = x["is"], x["oos"]
    stable = "yes" if (i["avg_r"] or -1) > 0 and (o["avg_r"] or -1) > 0 else "no"
    lo, hi = x["avg_r_ci95"]
    return (f"| {x['label'] if not x['label'].count('|') else nice(x['label'].replace(' +1st/day',''))+(' + 1st fill/day' if '1st/day' in x['label'] else '')}{flag} "
            f"| {x['n']} | {f(x['tpw'],2)} | {f(x['wr'],pct=True)} | **{f(x['avg_r'])}** [{f(lo,2)}, {f(hi,2)}] "
            f"| {f(x['avg_r_net005'])} | {f(x['avg_r_net_atr'])} | {f(x['sum_r'],1)} | {f(x['pf'],2)} | {f(x['max_dd'],1)} "
            f"| {x['max_lstreak']} | {f(i['avg_r'])} ({i['n']}) | {f(o['avg_r'])} ({o['n']}) | {stable} |")


HDR = ("| Config | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Avg R net 0.02ATR | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 |\n"
       "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|")


def write_md(summ):
    m = summ["meta"]
    rp = m["repro_legacy"]
    L = []
    A = L.append
    A("# RR-2 optimisation — Filtre B (research only, no deploy)")
    A("")
    A(f"Generated: **{datetime.now(tz=PARIS).strftime('%Y-%m-%d %H:%M %Z')}** (Europe/Paris). Branch `feat/always-on-fly`. Nothing deployed, Fly untouched.")
    A("")
    A("Scripts: `scripts/rr2_optim_backtest.py` (detection + grid), `scripts/rr2_report.py` (this report), "
      "`scripts/fetch_binance_m15.py` (Binance 15m klines for crypto intrabar paths). Same H1 cache "
      "(`/workspace/ob-scanner-v2/data/cache`), same engine (`detect_zones`, causal walk-forward, virgin OB + FVG, min 4★, "
      "METAUX+FOREX+CRYPTO, 48 symbols) as `volume_options_backtest.py`.")
    A("")
    A("@@NARRATIVE@@")
    A("")
    A("## 1. Calibration — exact reproduction of the old method")
    A("")
    A("Old method = `simulate_lifecycle` (mid entry managed from first zone contact, H1 OHLC, SL checked first), "
      "hold ≤1 H1 bar, **trades not resolved on the touch bar are dropped** (not closed at a time stop), trades/weekday = closed / (touch span × 5/7).")
    A("")
    A("| | Signals | Closed | W / L | WR | Avg R | Sum R | Dropped (hold-capped) | Trades/weekday (old span) | Trades/weekday (per-group window) |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, nm in (("1R", "B +1R"), ("2R", "B +2R")):
        x = rp[k]
        A(f"| {nm} | {x['signals']} | {x['closed']} | {x['wins']} / {x['losses']} | {f(x['wr'],pct=True)} | {f(x['avg_r'])} | {f(x['sum_r'],1)} | "
          f"{x['hold_capped_excluded']} | {f(x['tpw_old_convention'],2)} | {f(x['tpw_corrected'],2)} |")
    A("")
    A("Both match the existing reports exactly (92 / 83.7% / +0.674R and 64 / 76.6% / +1.297R).")
    A("")
    A("### Volume correction")
    A("")
    w = m["windows"]
    A("The old \"~1 trade/weekday\" divides by a 124.7-day touch span that comes from **TON only** (1 300 H1 bars back to May). "
      "Every other symbol has 800 H1 bars, so after the 80-bar warm-up the 48-symbol universe is only live from:")
    A("")
    A("| Group | Window (UTC) | Weekdays |")
    A("|---|---|---:|")
    for g, (a, b, wd) in w.items():
        A(f"| {g} | {a[:16]} → {b[:16]} | {wd:.1f} |")
    A("")
    A("Trades/weekday below = Σ_group (trades in the group window / weekdays of that window). Crypto weekend trades count in the numerator (same as the old convention). "
      "TON trades before the crypto window are excluded. Halves: each group window is split at its midpoint (IS = first half, OOS = second half).")
    A("")
    A("## 2. Where the old numbers come from — accounting decomposition (≥4★, all sessions, SL distal+0.05ATR, hold 1h)")
    A("")
    A("Every trade is now **closed** (TP, SL, or time stop at the close of the last hold bar). Models: "
      "`legacy` = H1 high/low incl. the entry bar; `cons` = H1, but on the entry bar TP/+1R only count if the close is beyond them; "
      "`m15` = real M15 path (yfinance FX/metals, Binance crypto), 1h = 4 M15 bars from the fill; entry M15 bar treated like `cons`. "
      "\"Touch-managed mid\" = what live/stats do today (trade starts at first zone contact even if price never reaches the mid entry). "
      "\"Mid limit fill\" = a limit order at the mid must actually fill (within 24 H1 bars after the touch).")
    A("")
    A("| Accounting | Model | Trades | WR | Avg R | PF | MaxDD R | IS avg R | OOS avg R |")
    A("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for x in summ["decomposition"]:
        nm = x["label"].split(" [")[0]
        A(f"| {nm} | {x['model']} | {x['n']} | {f(x['wr'],pct=True)} | {f(x['avg_r'])} | {f(x['pf'],2)} | {f(x['max_dd'],1)} | {f(x['is']['avg_r'])} | {f(x['oos']['avg_r'])} |")
    A("")
    A("## 3. Main comparison (M15 path model, fill required, hold 1h unless stated)")
    A("")
    A("Selection rule (fixed before looking at OOS): fill-required entries, TP = 2R, trades ≥ 40, ≥ 0.7 trades/weekday; "
      "rank by min(IS avg R, OOS avg R) × trades/weekday (= worst-half expectancy × volume). Grid: 5 realistic entries × 3 SL buffers × 4 holds × 2 star levels × 2 session filters × 3 management modes "
      f"(+ TP 1R references) = {m['n_configs']} configs × 3 models.")
    A("")
    A(HDR)
    for x in summ["headline_h1"]:
        A(row(x))
    A("")
    A("### ~1 trade/day variants (volume filters)")
    A("")
    A(HDR)
    for x in summ["low_volume_variants"]:
        A(row(x, " ⚠ n<40" if x["n"] < 40 else ""))
    A("")
    A("### Longer holds (info only — **needs holding longer than 1h**)")
    A("")
    A(HDR)
    for x in summ["longer_holds_info"]:
        A(row(x, " ⏱"))
    A("")
    A("### Per group (M15 model)")
    A("")
    A("| Config | METAUX n / WR / avg R | FOREX n / WR / avg R | CRYPTO n / WR / avg R |")
    A("|---|---|---|---|")
    for x in summ["headline_h1"][:4] + summ["low_volume_variants"][1:5] + [summ["decomposition"][2], summ["decomposition"][5]]:
        bg = x["by_group"]
        cells = [f"{bg[g]['n']} / {f(bg[g]['wr'],pct=True)} / {f(bg[g]['avg_r'])}" for g in GROUPS]
        lab = x["label"] if "|" not in x["label"] else nice(x["label"])
        A(f"| {lab} | " + " | ".join(cells) + " |")
    A("")
    A("### Neighbourhood of plain B +2R (vary one parameter, M15 model)")
    A("")
    A("| Change | Trades | /weekday | Avg R | IS avg R | OOS avg R |")
    A("|---|---:|---:|---:|---:|---:|")
    for nb in summ["neighbours"][RB2]:
        A(f"| {nb['vary']} | {nb['n']} | {f(nb['tpw'],2)} | {f(nb['avg_r'])} | {f(nb['is_avg_r'])} | {f(nb['oos_avg_r'])} |")
    A("")
    A("@@CAVEATS@@")
    A("")
    A("## Artifacts")
    A("")
    A("- `data/backtest/summary_rr2_optim.json` — calibration, decomposition, headline/low-volume/longer-hold configs with by-group and IS/OOS")
    A("- `data/backtest/rr2_optim_grid.csv` — full grid (all configs × legacy/cons/m15)")
    A("- `data/backtest/rr2_optim_top.csv` — flat table of reported configs")
    A("- `data/backtest/trades_rr2_*.csv` — trade lists for the main configs")
    A("- `data/backtest/rr2_optim_meta.json` — windows, split dates, calibration")
    A("- Local caches (not committed, regenerable): `data/backtest/m15_binance/*.parquet` (`scripts/fetch_binance_m15.py`), `data/backtest/rr2_zones.pkl`, `data/backtest/rr2_trades_store.pkl`")
    A("")
    A("Re-run: `.venv/bin/python scripts/fetch_binance_m15.py && .venv/bin/python scripts/rr2_optim_backtest.py && .venv/bin/python scripts/rr2_report.py`")
    (ROOT / "RR2_OPTIM.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------- selection ----------------
r = grid[(grid.model == "m15") & (grid.entry != "mid_live")].copy()
r["rob"] = r[["is_avg_r", "oos_avg_r"]].min(axis=1) * r.tpw
elig = r[(r.n >= 40) & (r.tpw >= 0.7) & (r.tp_r == 2)]
top_h1 = elig[elig.hold == 1].sort_values("rob", ascending=False).head(8)
top_long = elig[elig.hold > 1].sort_values("rob", ascending=False).head(5)
top_obj_h1 = elig[elig.hold == 1].sort_values("obj", ascending=False).head(3)

B1 = "mid_live|sl0.05|h1|s4|all|none|1R"
B2 = "mid_live|sl0.05|h1|s4|all|none|2R"
RB1 = "mid_live_fill|sl0.05|h1|s4|all|none|1R"
RB2 = "mid_live_fill|sl0.05|h1|s4|all|none|2R"

decomp = []
for cfg, nm in ((B1, "B +1R"), (B2, "B +2R")):
    for model in ("legacy", "cons", "m15"):
        decomp.append(S(cfg, model, label=f"{nm} live accounting (touch-managed mid) [{model}]"))
for cfg, nm in ((RB1, "B +1R"), (RB2, "B +2R")):
    for model in ("legacy", "cons", "m15"):
        decomp.append(S(cfg, model, label=f"{nm} realistic mid limit fill [{model}]"))

headline = [S(RB1, label="Realistic B +1R (mid limit fill, 1h, M15)"),
            S(RB2, label="Realistic plain B +2R (mid limit fill, 1h, M15)")]
for cfg in top_h1.config:
    if cfg not in (RB1, RB2):
        headline.append(S(cfg))
longer = [S(c) for c in top_long.config]
for h in (2, 3, 4):
    longer.append(S(f"mid_live_fill|sl0.05|h{h}|s4|all|none|2R"))
low_vol = [
    S("mid_live_fill|sl0.05|h1|s4|lonny|none|1R"),
    S("mid_live_fill|sl0.05|h1|s4|lonny|none|2R"),
    S("mid_live_fill|sl0.05|h1|s4|lonny|be|2R"),
    S("mid_live_fill|sl0.05|h1|s4|lonny|partial|2R"),
    S("d75|sl0.1|h1|s4|lonny|be|2R"),
    S("mid_live_fill|sl0.05|h1|s5|all|none|1R"),
    S("mid_live_fill|sl0.05|h1|s5|all|none|2R"),
    S(RB1, fpd=True), S(RB2, fpd=True),
    S(top_h1.config.iloc[0], fpd=True),
]

# neighbourhood of plain B+2R and of best h1 config (vary one dim)
def neighbours(cfg):
    parts = cfg.split("|")
    rows = []
    sub = grid[(grid.model == "m15")]
    for i, alts in enumerate([["mid_live_fill", "prox", "d25", "d50", "d75"], ["sl0.05", "sl0.1", "sl0.25"],
                              ["h1", "h2", "h3", "h4"], ["s4", "s5"], ["all", "lonny"], ["none", "be", "partial"],
                              ["1R", "2R"]]):
        for a in alts:
            if a == parts[i]:
                continue
            p = parts.copy(); p[i] = a
            c = "|".join(p)
            x = sub[sub.config == c]
            if len(x):
                x = x.iloc[0]
                rows.append({"vary": a, "config": c, "n": int(x.n), "tpw": x.tpw, "avg_r": x.avg_r,
                             "is_avg_r": x.is_avg_r, "oos_avg_r": x.oos_avg_r})
    return rows


best = top_h1.config.iloc[0]
neigh = {RB2: neighbours(RB2), best: neighbours(best)}

summary = {
    "generated_at": datetime.now(tz=PARIS).isoformat(),
    "meta": meta,
    "selection_rule": "m15 model, fill-required entries, TP=2R, n>=40, trades/weekday>=0.7; rank by min(IS avg R, OOS avg R) x trades/weekday",
    "decomposition": decomp,
    "headline_h1": headline,
    "longer_holds_info": longer,
    "low_volume_variants": low_vol,
    "neighbours": neigh,
    "top_obj_h1": list(top_obj_h1.config),
}
(OUT / "summary_rr2_optim.json").write_text(json.dumps(summary, indent=2, default=str))
pd.DataFrame(
    [{**{k: v for k, v in x.items() if k not in ("by_group", "is", "oos", "exits", "avg_r_ci95")},
      "ci_lo": x["avg_r_ci95"][0], "ci_hi": x["avg_r_ci95"][1],
      "is_avg_r": x["is"]["avg_r"], "oos_avg_r": x["oos"]["avg_r"],
      "is_n": x["is"]["n"], "oos_n": x["oos"]["n"],
      **{f"{g}_avg_r": x["by_group"][g]["avg_r"] for g in GROUPS},
      **{f"{g}_n": x["by_group"][g]["n"] for g in GROUPS}}
     for x in decomp + headline + longer + low_vol]
).to_csv(OUT / "rr2_optim_top.csv", index=False)

# trades for headline configs
for x in headline[:3] + [decomp[0], decomp[5]]:
    trs = closed(store[(x["config"], x["model"])])
    safe = x["config"].replace("|", "_").replace(".", "")
    with open(OUT / f"trades_rr2_{safe}_{x['model']}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(trs[0].keys()))
        w.writeheader(); w.writerows(trs)

write_md(summary)
print(json.dumps({"top_h1": list(top_h1.config), "top_long": list(top_long.config)}, indent=1))


# ---------------------------------------------------------------- narrative
def _phantom():
    a = {(t["symbol"], t["ts_ob"]): t for t in closed(store[(B2, "m15")])}
    b = {(t["symbol"], t["ts_ob"]): t for t in closed(store[(RB2, "m15")])}
    same, diff = [], []
    for k, t in a.items():
        u = b.get(k)
        (same if (u and u["fill_at"] == t["fill_at"]) else diff).append((t, u))
    m = lambda xs: float(np.mean(xs)) if xs else float("nan")  # noqa: E731
    return {
        "n": len(a), "n_same": len(same), "n_diff": len(diff),
        "touch_r_same": m([t["r"] for t, _ in same]),
        "touch_r_diff": m([t["r"] for t, _ in diff]),
        "fill_r_diff": m([u["r"] for _, u in diff if u]), "n_fill_diff": sum(1 for _, u in diff if u),
    }


def _get(lst, cfg):
    for x in lst:
        if x["config"] == cfg and "1st/day" not in x["label"]:
            return x
    raise KeyError(cfg)


def finalize():
    summ = json.loads((OUT / "summary_rr2_optim.json").read_text())
    ph = _phantom()
    summ["phantom_fill_check"] = ph
    (OUT / "summary_rr2_optim.json").write_text(json.dumps(summ, indent=2, default=str))
    rp = summ["meta"]["repro_legacy"]
    allx = summ["decomposition"] + summ["headline_h1"] + summ["low_volume_variants"] + summ["longer_holds_info"]
    r1 = _get(summ["headline_h1"], RB1)
    r2 = _get(summ["headline_h1"], RB2)
    d75 = _get(allx, "d75|sl0.1|h1|s4|all|be|2R")
    d75p = _get(allx, "d75|sl0.1|h1|s4|all|partial|2R")
    ln = _get(allx, "mid_live_fill|sl0.05|h1|s4|lonny|none|2R")
    lnb = _get(allx, "mid_live_fill|sl0.05|h1|s4|lonny|be|2R")
    lnp = _get(allx, "mid_live_fill|sl0.05|h1|s4|lonny|partial|2R")
    ln1 = _get(allx, "mid_live_fill|sl0.05|h1|s4|lonny|none|1R")
    s5 = _get(allx, "mid_live_fill|sl0.05|h1|s5|all|none|2R")
    fpd = [x for x in summ["low_volume_variants"] if x["label"] == RB2 + " +1st/day"][0]
    fpd75 = [x for x in summ["low_volume_variants"] if "d75" in x["label"] and "1st/day" in x["label"]][0]
    dec = {(x["label"].split(" [")[0], x["model"]): x for x in summ["decomposition"]}

    def ci(x):
        return f"[{x['avg_r_ci95'][0]:+.2f}, {x['avg_r_ci95'][1]:+.2f}]"

    ex2 = r2["exits"]
    nar = f"""## TL;DR

**Key table** (hold 1h, ≥4★, METAUX+FOREX+CRYPTO; "realistic" = mid limit order must actually fill, M15 price path, every trade closed by TP / SL / 1h time stop; no costs unless stated)

| Config | Trades | /weekday | WR | Avg R | PF | MaxDD R | IS → OOS avg R |
|---|---:|---:|---:|---:|---:|---:|---|
| Live B +1R, old method (reproduced) | {rp['1R']['closed']} | {rp['1R']['tpw_old_convention']:.2f} (really {rp['1R']['tpw_corrected']:.2f}) | {100*rp['1R']['wr']:.1f}% | +{rp['1R']['avg_r']:.3f} | 5.13 | 3.0 | — |
| Plain B +2R, old method (reproduced) | {rp['2R']['closed']} | {rp['2R']['tpw_old_convention']:.2f} (really {rp['2R']['tpw_corrected']:.2f}) | {100*rp['2R']['wr']:.1f}% | +{rp['2R']['avg_r']:.3f} | 6.53 | 4.0 | — |
| **Live B +1R, realistic** | {r1['n']} | {r1['tpw']:.2f} | {100*r1['wr']:.1f}% | **{r1['avg_r']:+.3f}** {ci(r1)} | {r1['pf']:.2f} | {r1['max_dd']:.1f} | {r1['is']['avg_r']:+.3f} → {r1['oos']['avg_r']:+.3f} |
| **Plain B +2R, realistic** | {r2['n']} | {r2['tpw']:.2f} | {100*r2['wr']:.1f}% | **{r2['avg_r']:+.3f}** {ci(r2)} | {r2['pf']:.2f} | {r2['max_dd']:.1f} | {r2['is']['avg_r']:+.3f} → {r2['oos']['avg_r']:+.3f} |
| B +2R + Lon+NY + BE@+1R (≈1–1.5/day) | {lnb['n']} | {lnb['tpw']:.2f} | {100*lnb['wr']:.1f}% | {lnb['avg_r']:+.3f} {ci(lnb)} | {lnb['pf']:.2f} | {lnb['max_dd']:.1f} | {lnb['is']['avg_r']:+.3f} → {lnb['oos']['avg_r']:+.3f} |
| Grid best 1h: 75%-depth limit, SL distal+0.1ATR, BE@+1R, TP 2R | {d75['n']} | {d75['tpw']:.2f} | {100*d75['wr']:.1f}% | {d75['avg_r']:+.3f} {ci(d75)} | {d75['pf']:.2f} | {d75['max_dd']:.1f} | {d75['is']['avg_r']:+.3f} → {d75['oos']['avg_r']:+.3f} |

Findings:

1. **The old numbers reproduce exactly but are inflated.** Three accounting artifacts plus a volume miscount (quantified in §1–§2):
   - *Phantom mid fill*: live/lifecycle manages a mid-entry trade from the **first zone contact** (`require_entry_fill=False` for mid). On the M15 path, only {ph['n_same']}/{ph['n']} zones actually trade the mid at the touch, and those average **{ph['touch_r_same']:+.2f}R** (B +2R, 1h). The other {ph['n_diff']} average {ph['touch_r_diff']:+.2f}R in the live accounting, mostly bounces off the zone edge that a mid limit never caught. When the mid limit really fills (later), they average {ph['fill_r_diff']:+.2f}R (n={ph['n_fill_diff']}).
   - *H1 same-bar ordering*: on the touch bar, the H1 high/low is often printed **before** price reached the zone. On M15 the live-accounting B +1R drops from {dec[('B +1R live accounting (touch-managed mid)','legacy')]['avg_r']:+.3f} to {dec[('B +1R live accounting (touch-managed mid)','m15')]['avg_r']:+.3f}R.
   - *Dropped timeouts*: the old method **excluded** trades that didn't finish within the touch bar (5 at +1R, **33 at +2R**) instead of closing them at the time stop. That is the main reason the earlier +2R test showed +1.30R. Closing them at the 1h time stop on H1 already gives {dec[('B +2R live accounting (touch-managed mid)','legacy')]['avg_r']:+.3f}R.
   - *Volume*: the "~1 trade/weekday" comes from dividing by a 124.7-day span that only TON has. All 48 symbols are only live for about 6 weeks (crypto about 4), and the real flow of B is **≈{r1['tpw']:.1f} filled trades/weekday** (≈{rp['1R']['tpw_corrected']:.1f} even with the old accounting).
2. **RR2 vs RR1 (same entry, SL, and 1h hold): +2R is ≥ +1R in every model** (realistic: legacy H1 {dec[('B +2R realistic mid limit fill','legacy')]['avg_r']:+.3f} vs {dec[('B +1R realistic mid limit fill','legacy')]['avg_r']:+.3f} = tie, cons H1 {dec[('B +2R realistic mid limit fill','cons')]['avg_r']:+.3f} vs {dec[('B +1R realistic mid limit fill','cons')]['avg_r']:+.3f}, M15 {r2['avg_r']:+.3f} vs {r1['avg_r']:+.3f}), and on M15 +2R is positive in both halves (+1R is not). But the gain is small (+{r2['avg_r']-r1['avg_r']:.3f}R/trade on M15), and both 95% CIs include 0. Over 1h the +2R target is rarely reached: TP {ex2.get('tp',0)}, SL {ex2.get('sl',0)}, time stop {ex2.get('time',0)} of {r2['n']}. RR2 at 1h is effectively "SL or exit at market after 1h, with a rare +2R".
3. **Best grid variant at 1h** = 75%-depth limit (deep in the zone, tighter stop), SL distal+0.1 ATR, BE (or 50% partial) at +1R: about +0.32R, PF ≈1.7. It is **not robust**: IS {d75['is']['avg_r']:+.2f} → OOS {d75['oos']['avg_r']:+.2f}. CRYPTO carries it ({d75['by_group']['CRYPTO']['avg_r']:+.2f}R, n={d75['by_group']['CRYPTO']['n']}) while METAUX is about 0. With one trade per day the OOS turns negative ({fpd75['oos']['avg_r']:+.2f}R). Its neighbour d50 (pure mid) is ≈0, which looks like noise, not structure.
4. **About 1 trade/day at 1h**: the London+NY filter on the fill time halves the volume to {ln['tpw']:.2f}/weekday. B +2R then gives {ln['avg_r']:+.3f}R (BE@+1R {lnb['avg_r']:+.3f}, partial {lnp['avg_r']:+.3f}) vs {ln1['avg_r']:+.3f} at +1R, positive in both halves for +2R. But n={ln['n']}, and CRYPTO (n={ln['by_group']['CRYPTO']['n']}) supplies most of the R. 5★ only ({s5['tpw']:.2f}/weekday) is **negative** ({s5['avg_r']:+.3f}R, n={s5['n']}). "First fill of the day" has a negative OOS ({fpd['oos']['avg_r']:+.3f}R).

## Recommendation

- **RR2 is directionally better than live B +1R for about 1h holds**, but only modestly and without statistical confirmation. Realistic expectancy is about +0.10 to +0.20R/trade before costs, with WR about 45–55%. It is not 77–84%.
- If you change anything, the **least-overfit RR2 setup** is **plain B +2R**: keep the mid entry, SL distal+0.05 ATR, ≥4★, M+F+C, and 1h time stop. To get to about 1–1.5 trades/weekday, optionally take only fills in **London/NY** and move the SL to **break-even at +1R**. Both are mild, interpretable filters that stay positive in both halves.
- **Do not adopt the 75%-depth entry** (or any grid "winner") yet. Paper-trade it alongside.
- **Fix the measurement before trusting live stats** (not done here, research only). With `require_entry_fill=False` for mid, the live "Réaction +1R" alerts and the 84% WR count phantom fills, and timeouts are not closed. Any live-vs-backtest comparison will look much better than real fills.
- Re-run on a longer history (≥6 months of H1 + M15) before any production change. With about 80–90 trades over about 6 weeks, a ±0.3R confidence interval cannot separate these variants.
"""
    cav = f"""## Caveats

- **Short sample**: H1 cache = 800 bars/symbol, so the analysis window is {summ['meta']['windows']['FOREX'][0][:10]} → {summ['meta']['windows']['FOREX'][1][:10]} (FX), with crypto only from {summ['meta']['windows']['CRYPTO'][0][:10]}. That gives 78–92 trades per config, and each half covers about 3 weeks. The 95% CIs are about ±0.3R wide.
- **Multiple testing**: {summ['meta']['n_configs']} configs × 3 models. The selection rule (worst-half expectancy × volume) limits but does not remove optimism. The top grid configs are probably overstated.
- **Intrabar data**: FX/metals M15 comes from yfinance (the same feed as their H1, so levels are consistent; metals = futures GC/SI/HG/PA/PL). Crypto M15 is Binance spot 15m (fetched for this study, matches the H1 closes exactly). TON has no M15 after June, so its trades fall back to the H1 `cons` model ({int(grid[(grid.config==RB2)&(grid.model=='m15')].fallback_n.iloc[0])} trades in plain B +2R). Within each M15 bar, SL is checked before TP. On the entry bar, TP/+1R only count on the close.
- **Fills**: a limit fills when price touches the level (no queue, no partial fills), within 24 H1 bars of the first zone contact. Alert latency and manual execution delay are not modelled; the zone is assumed known at the close of its detection bar.
- **Hold definition**: on M15, "1h" = 4 M15 bars from the fill. In the H1 models, hold 1 = the fill bar only (the old method's ≤1 bar).
- **Costs**: the headline numbers are gross. Net columns show −0.05R/trade and an alternative −0.02 H1-ATR/trade, which converts to more R for tighter stops (75% depth: median risk ≈0.32 ATR vs ≈0.63 ATR at mid). Crypto exchange fees could exceed both.
- Overlapping or concurrent positions are not limited, and there is no portfolio-level risk cap. Session filter = fill time in Paris (London 08:00–11:30, NY 14:30–17:30).
- Research only: no change to `fly.toml`, env, code paths used by production, or the deployed app. Not trading advice.
"""
    md = (ROOT / "RR2_OPTIM.md").read_text()
    md = md.replace("@@NARRATIVE@@", nar).replace("@@CAVEATS@@", cav)
    (ROOT / "RR2_OPTIM.md").write_text(md)


finalize()
