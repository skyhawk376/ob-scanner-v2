#!/usr/bin/env python3
"""Write MOMENTUM_FILTER.md from outputs of momentum_filter_backtest.py (no recomputation)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "backtest"
PARIS = ZoneInfo("Europe/Paris")


def f(x, d=3, pct=False, sign=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    if pct:
        return f"{100 * x:.1f}%"
    if x == float("inf"):
        return "∞"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def row(r, label=None):
    flag = " ⚠ n<40" if r["n"] < 40 else ""
    both = "yes" if r["both_halves_pos"] else "no"
    rej = ""
    if "rej_n" in r and not pd.isna(r.get("rej_n")):
        rej = f"{int(r['rej_n'])} / {f(r['rej_avg_r'], sign=True)} / {f(r['perm_p'], 3)}"
    return (f"| {label or r['variant']}{flag} | {int(r['n'])} | {f(r['tpw'], 2)} | {f(r['wr'], pct=True)} | "
            f"**{f(r['avg_r'], sign=True)}** [{f(r['ci_lo'], 2)}, {f(r['ci_hi'], 2)}] | {f(r['avg_r'] - 0.05 if r['n'] else None, sign=True)} | "
            f"{f(r['sum_r'], 1)} | {f(r['pf'], 2)} | {f(r['max_dd'], 1)} | {int(r['max_lstreak'])} | "
            f"{f(r['is_avg_r'], sign=True)} ({int(r['is_n'])}) | {f(r['oos_avg_r'], sign=True)} ({int(r['oos_n'])}) | {both} | {rej or '—'} |")


HDR = ("| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | "
       "IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |\n"
       "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|")


def main():
    s = json.loads((OUT / "summary_momentum_filter.json").read_text())
    v = pd.DataFrame(s["variants"])
    sens = pd.DataFrame(s["fill_sensitivity"])
    old = pd.DataFrame(s["old_method_reference"])
    ema = pd.DataFrame(s["ema_length_check"])

    def get(tp, d, tfs):
        q = v[(v.tp == tp) & (v.bias_def == d) & (v.tfs == tfs)]
        return q.iloc[0]

    b1, b2 = get("1R", "-", "-"), get("2R", "-", "-")
    heads = [("D1", "ema50"), ("H4+D1", "ema50"), ("H1+H4+D1", "ema50"), ("ALL(M15+H1+H4+D1)", "ema50"),
             ("ALL>=N-1", "ema2050")]
    L = []
    gen = datetime.fromisoformat(s["generated_at"]).astimezone(PARIS).strftime("%Y-%m-%d %H:%M %Z")
    L += ["# Multi-timeframe momentum alignment filter on Filtre B (research only, no deploy)", "",
          f"Generated: **{gen}** (Europe/Paris). Branch `feat/always-on-fly`. Nothing deployed, Fly untouched.", "",
          "Scripts: `scripts/momentum_filter_backtest.py` (bias + variants), `scripts/momentum_filter_report.py` (this file). "
          "Trade simulation is the **realistic simulator of `scripts/rr2_optim_backtest.py`** (imported unchanged): "
          "mid limit must actually fill (≤24 H1 bars after first touch), M15 price path (yfinance FX/metals, Binance crypto; "
          "H1-conservative fallback when no M15), every trade closed by TP / SL / **1h time stop**. Same causal zone detection "
          "(`rr2_zones.pkl`), same group windows, same IS/OOS split (each group window cut at its midpoint) and the same "
          "trades/weekday convention as `RR2_OPTIM.md`, so the baseline reproduces it exactly (88 trades, 55.7% / +0.104R at +1R; "
          "51.1% / +0.142R at +2R).", ""]

    # TL;DR
    L += ["## TL;DR", "", "Realistic simulator, hold 1h, ≥4★, METAUX+FOREX+CRYPTO, entry mid (fill required), SL distal+0.05 ATR. "
          "Bias measured at the OB touch time on closed candles only. No costs except the \"net\" column.", "", HDR]
    for tp, b in (("1R", b1), ("2R", b2)):
        L.append(row(b, f"**B baseline +{tp}**"))
        for tfs, d in heads:
            r = get(tp, d, tfs)
            L.append(row(r, f"B + {tfs} [{d}] +{tp}"))
    L += ["",
          "Reading: `D1 [ema50]` = trade only if the last closed D1 close is on the OB side of the D1 EMA50 (bull OB: close > EMA50). "
          "`H4+D1` = both H4 and D1 agree. `ALL>=N-1` = at most one of M15/H1/H4/D1 disagrees. "
          "`Rejected` = trades the filter removes (their avg R) and a one-sided permutation p-value for selected − rejected.", ""]

    best1 = s["best_1R"]
    L += ["### Findings", "",
          f"1. **The momentum effect is real in this sample but comes from the higher TFs (D1, then H4).** With the fixed selection rule "
          f"(n ≥ 40, rank by worst-half avg R × trades/weekday, set before looking at results), the winner at both +1R and +2R is "
          f"**B + D1 trend (close vs EMA50)**: {int(best1['n'])} trades, {f(best1['tpw'],2)}/weekday, WR {f(best1['wr'],pct=True)}, "
          f"{f(best1['avg_r'],sign=True)}R at +1R (baseline {f(b1['avg_r'],sign=True)}R). Both halves positive, and the removed trades average "
          f"{f(best1['rej_avg_r'],sign=True)}R.",
          "2. **Adding H4 (H4+D1, EMA-based) is the best \"≈1 trade/day\" variant**: 35 trades, 1.35/weekday, WR 65.7%, +0.328R (+1R) / "
          "+0.423R (+2R), PF 2.9–3.2, max DD 1.7R, both halves positive. It is slightly below the 40-trade bar, so it is flagged.",
          "3. **Full alignment (Kasper \"all TFs aligned\") is too restrictive at 1h hold.** ALL(M15+H1+H4+D1) leaves 11 trades with EMA50 bias "
          "(+0.46R at +1R, 0.41/weekday). With strict market structure it leaves 0. H1+H4+D1 gives 19 trades (0.68/weekday, +0.47R / +0.62R). "
          "These look best per trade, but n is too small to trust and the volume drops well below 1/day.",
          "4. **The market-structure bias (HH/HL vs LH/LL, fractal n=3) does not work as a filter here.** It is neutral (\"range\") on 25–55% "
          "of touches, so multi-TF variants collapse to <10 trades. D1 structure alone helps a little (+0.21R, n=32), and H4 structure gives nothing.",
          "5. **Robust to the EMA length**: D1 close vs EMA20/30/50/100/200 all give +0.21 to +0.25R at +1R and +0.29 to +0.33R at +2R, "
          "with n 48–51 and both halves positive. H4+D1 with EMA100/200 keeps n ≥ 40 (43/47 trades, +0.30/+0.26R at +1R). "
          "The control (H4+D1 *against* the OB) is about 0R (+0.02R at +1R, +0.04R at +2R).",
          "6. **+2R ≥ +1R for every EMA-based momentum variant** (D1: +0.329 vs +0.247; H4+D1: +0.423 vs +0.328), as in RR2. Most +2R trades still "
          "exit at the 1h time stop (D1: 31 time / 6 TP / 11 SL).",
          "7. **Statistical caution.** About 21 filter variants × 2 TPs were tested, plus the EMA-length check. The best single "
          "permutation p-values are ~0.007–0.05, which do not survive a multiple-testing correction. The 95% bootstrap CIs of the filtered "
          "variants exclude 0 (D1: [+0.02, +0.46] at +1R), while the baseline's do not. Evidence is **suggestive, not conclusive**.", ""]

    # Recommendation
    L += ["## Recommendation", "",
          "- **Add a D1 trend gate, but first as a shadow tag, not a hard live filter.** Log the D1 bias (close vs D1 EMA50) and the H4 bias on every "
          "Filtre B alert and track the realistic outcome (actual mid fill, 1h time stop) for 4–6 more weeks. If the aligned/non-aligned "
          "split holds, switch it on.",
          "- If you want to switch now, use the **D1-only gate** (≥40 trades, robust across EMA lengths, ≈1.9 trades/weekday). Use "
          "**H4+D1** if you prefer to be closer to **≈1 trade/day** (1.35/weekday, highest quality among variants with ≥35 trades). "
          "Keep TP +2R if RR2 is adopted, since the filter and +2R stack.",
          "- **Do not adopt \"all TFs aligned\"** (M15+H1+H4+D1): it leaves ~0.4 trades/weekday and 11 trades in 6 weeks.",
          "- Expect realistic numbers around 60–65% WR and +0.25 to +0.4R/trade before costs, **not** the 84% / +0.67R of the old method.", ""]

    # Method
    L += ["## Method", "",
          "- **Bias time**: the open of the H1 touch bar (first zone contact). A TF bar counts only once fully closed "
          "(open + duration ≤ T; D1 bars dated d count from d+1 00:00 UTC). No lookahead.",
          "- **TFs**: M15 = simulator M15 source (cache yfinance M15 for FX/metals, Binance M15 for crypto). "
          "H1 = H1 cache plus earlier history from cache M15 resampled. H4 = UTC 4h resample of that H1. "
          "D1 = yfinance daily (fetched once into `data/backtest/momentum_d1/`; GC=F/SI=F/PL=F/PA=F/HG=F for metals, `=X` FX, `-USD` crypto, SUI = SUI20947-USD). "
          f"Missing: **M15 for {', '.join(s['missing_m15_symbols']) or 'none'}** (Binance TON M15 ends June → skipped for TON). "
          f"**D1 for {', '.join(s['d1_resampled_from_h1_symbols']) or 'none'}** comes from an UTC resample of TON H1 (no correct Yahoo ticker). "
          "W1 not used (not requested; would need its own fetch). A missing/stale TF is skipped in the alignment test.",
          "- **Bias definitions**: `struct` = last 2 confirmed fractal swing highs and lows (n=3, confirmed n bars later): HH+HL bull, LH+LL bear, "
          "else neutral. `ema50` = last closed close vs EMA50. `ema2050` = EMA20 vs EMA50. ≥50 closed bars are needed, otherwise neutral.",
          "- **Alignment**: bull OB needs bullish bias (bear OB bearish); neutral counts as not aligned. `ALL>=N-1` = aligned on all available TFs but one. "
          "`no-opposite` = no TF against (neutral allowed; same as `all` for EMA defs).",
          "- **Selection rule** (as in RR2, fixed in code): n ≥ 40, max of min(IS avg R, OOS avg R) × trades/weekday. "
          "Variants with n < 40 are flagged ⚠ and cannot win.",
          f"- Windows (UTC): " + "; ".join(f"{g} {a[:16]} → {b[:16]} ({w:.1f} weekdays)" for g, (a, b, w) in s["windows"].items())
          + ". Trades/weekday = Σ_group trades / group weekdays.", ""]

    # Full tables
    for tp in ("1R", "2R"):
        L += [f"## All variants — TP +{tp}", "", HDR]
        q = v[v.tp == tp]
        for _, r in q.iterrows():
            lab = r["variant"] if r["bias_def"] == "-" else f"{r['variant']} [{r['bias_def']}]"
            L.append(row(r, lab))
        L.append("")

    L += ["## Per group (WR / avg R, n)", "",
          "| Variant | TP | METAUX | FOREX | CRYPTO |", "|---|---|---|---|---|"]
    for tp in ("1R", "2R"):
        for tfs, d in [("-", "-")] + heads[:3] + [("H4+D1 against", "ema50")]:
            r = get(tp, d, tfs)
            cells = [f"{int(r[f'{g}_n'])} / {f(r[f'{g}_wr'], pct=True)} / {f(r[f'{g}_avg_r'], sign=True)}" for g in ("METAUX", "FOREX", "CRYPTO")]
            lab = "B baseline" if d == "-" else f"B + {tfs} [{d}]"
            L.append(f"| {lab} | +{tp} | " + " | ".join(cells) + " |")
    L += ["", "Most METAUX OBs in this window ran against the H4/D1 trend: 12 of 16 trades are *against* H4+D1. The filter therefore keeps "
          "only 4 metal trades, and the gain comes from FOREX and CRYPTO.", ""]

    L += ["## Robustness — EMA length (close vs EMA_span)", "", HDR]
    for _, r in ema.iterrows():
        L.append(row(r, f"{r['variant']} +{r['tp']}"))
    L += ["", "## Sensitivity — bias at fill time instead of touch time", "", HDR]
    for _, r in sens.iterrows():
        L.append(row(r, f"{r['variant']} [{r['bias_def']}] +{r['tp']}"))
    L += ["", "## Old method (reference only — inflated, do not use for decisions)", "",
          "Old method = `simulate_lifecycle`, mid managed from first contact, H1 OHLC, unresolved trades **dropped** (see RR2_OPTIM.md §1).", "",
          "| Variant | TP | Closed | WR | Avg R | PF | Trades/weekday (per-group windows) |", "|---|---|---:|---:|---:|---:|---:|"]
    for _, r in old.iterrows():
        L.append(f"| {r['variant']} | +{r['tp']} | {int(r['n'])} | {f(r['wr'], pct=True)} | {f(r['avg_r'], sign=True)} | {f(r['pf'], 2)} | {f(r['tpw_corrected'], 2)} |")
    L += ["", "## Caveats", "",
          "- **Sample size**: ~6 weeks (crypto ~4) of H1, 88 baseline trades. Filtered variants have 11–51 trades. One market regime. "
          "Many variants were tested (see Findings 7).",
          "- **No costs/slippage/spread** in the main metrics. The \"net 0.05R\" column subtracts a flat 0.05R/trade (RR2 convention).",
          "- D1 for metals comes from **futures** (GC=F etc.), while trades use spot/OANDA-like H1. The trend sign is the same in practice, but the levels differ.",
          "- H4 is a UTC-aligned resample (00/04/08… UTC). Broker H4 candles (e.g. NY-close aligned) can differ slightly.",
          "- TON: no M15 path after June (simulator falls back to H1-conservative) and D1 is resampled from H1.",
          "- The realistic simulator still assumes a resting limit at the mid for 24 H1 bars after the touch, and conservative fill-bar handling.",
          "- Research only: nothing changed in the scanner, API, Telegram or Fly.", ""]
    (ROOT / "MOMENTUM_FILTER.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote MOMENTUM_FILTER.md", len(L))


if __name__ == "__main__":
    main()
