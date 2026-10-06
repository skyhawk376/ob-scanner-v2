# Pre-registration #4 — OB-only final study (HTF swing, HTF zone + LTF confirmation, indices, management, ≤3h)

Written 2026-10-06 (Europe/Paris) **before any backtest of this study was run**. Research only: no deploy, no push.
Scripts: `scripts/strategy_research/ob_final/`. Outputs: `data/backtest/strategy_research/ob_final/`.
Constraint from the user: **order blocks only** ("juste les OBs"). Every family below is an OB strategy.

## 0. What already failed (not repeated as-is)
Intraday engine-5★ OBs M5–H1 with 1–3h holds (all assets, XAU-only; ≈0R gross, negative net); strict 5★ virgin H4/D1/W
engine zones (too few). Near-miss: H1 OB ≥4★ + D1 trend on indices (+0.137R n=76 TRAIN / +0.041R n=29 TEST).

## 1. Data and split
* 17 assets: 11 FX (EURUSD GBPUSD USDJPY USDCAD AUDUSD USDCHF EURJPY GBPJPY EURGBP), XAUUSD, XAGUSD, US500, NAS100, DAX
  (HistData = Dukascopy BID M1, extended back to **2015-01**), BTC/ETH (Binance spot M1 from 2017-08), SOL (from 2020-08).
  If a HistData year is missing for an asset, that asset simply starts later (documented in the report).
* First 120 calendar days of each asset = warm-up only (no trades).
* **TRAIN = fills before 2022-01-01. TEST = fills 2022-01-01 → 2026-09-30.** (Applies to all families; holds are hours→days,
  the long history gives far larger samples than the 2025-07 split.) The **2025-07-01 → 2026-09-30** slice of TEST
  ("RECENT", same as the earlier studies' test) is reported for information, never used for selection.

## 2. Execution and costs (framework, unchanged)
* `common._sim` conventions: order live **3 min after the signal bar closes**; limit fills only on trade-through by half the
  spread; stop/market legs pay half-spread + slippage; SL first when SL and TP are both reachable in the same M1 bar;
  on the fill bar TP counts only on a close beyond it; time stop = market exit. A dedicated numba simulator in
  `ob_final/core.py` reproduces `_sim` exactly when management is off (checked, see report) and adds management.
* Costs = `common.costs` (spread, round-trip commission, slippage per stop/market leg).
* **Swap (new, holds up to 10 days)**: charged per calendar day in the trade (≈ triple-Wednesday averaged), as an annual
  rate on price, **both sides pay** (conservative; positive carry ignored):
  FX 1.5% long / 1.5% short; metals 7.3% / 3.65%; indices 6% / 2%; crypto 10% / 3%.
* Stress: 1.5× all costs (spread, commission, slippage, swap). Gross = zero cost (no spread, no slippage, no swap).

## 3. OB definition ("OBX", broad and well-defined; star score = filter, not requirement)
On TF bars (H1, H4 = UTC-aligned buckets; D1 = 17:00 New York roll, crypto UTC day), ATR14 (Wilder) of the TF:
* Pivots: strict fractals (engine `find_pivots`), n = 3 for H1/H4, n = 2 for D1, confirmed n bars later.
* **Bull BOS at bar j**: close[j] > price of the most recent pivot high confirmed by j, first time for that pivot.
  Leg low k = argmin low over [pivot .. j]. **OB = last bearish candle (close<open) at or before k** (≤ 10 bars back).
  Zone = [low, high] of the OB candle. Bear = mirror. (Same structure as the engine, without its hard filters.)
* Variants of the definition: **BOS** (as above) or **BOS+FVG** (additionally ≥1 three-candle FVG in the zone direction
  whose middle candle lies in (ob, j]).
* Validity: no bar in [ob+3, j] intersects the zone (engine virgin rule). Zone becomes known at the close of bar
  max(j, ob+2); order/alert live 3 min later. Pending until the **first touch**; expiry H1 5 days, H4 15 days, D1 40 days.
* Stars at confirmation (★5 session not used for zones): ★1 FVG at OB (high[ob] < low[ob+2] bull); ★2 pivot trend
  HH+HL (bull) before j; ★3 whole zone in discount (zone high ≤ 50% of [leg low, highest high k..j]) ; ★4 no untaken
  pivot low within 1 ATR below the zone (engine tolerance). score4 = ★1+★2+★3+★4. Filter: **any** or **score4 ≥ 3**.
* D1 trend filter: last closed D1 close vs EMA50 (EMA20 also in family C) aligned with zone direction.

## 4. Families and grids (compact)
**A. HTF OB swing, all 17 assets.** TF {H4, D1} × def {BOS, BOS+FVG} × stars {any, ≥3} × trend {none, D1 EMA50}
× entry {limit proximal, limit mid} × TP {2R, 3R, LIQ} × max hold {5d, 10d} = **192**.
SL = distal − 0.2 ATR(TF). LIQ = the leg extreme (highest high since k on TF bars, updated with M1 highs until the fill);
trade skipped if LIQ < 1.5R from entry at the fill.

**B. HTF zone + LTF confirmation (classic SMC), all 17 assets.** Zones = family-A BOS zones. Tap = first M1 touch of the
proximal edge after the zone is live (within expiry). Watch LTF bars for W = 24h (H4 zone) / 48h (D1 zone) after the tap.
Invalidated if an LTF bar closes beyond the distal edge first. **Bull CHoCH** = an LTF close above the most recent
confirmed LTF pivot high (n=2) formed no earlier than 24 LTF bars before the tap bar. Entry = market 3 min after that
LTF bar closes. Grid: zone TF {H4, D1} × stars {any, ≥3} × LTF {M5, M15} × trend {none, D1 EMA50} × SL {LTF: lowest low
since tap − 0.1 ATR(LTF); ZONE: distal − 0.2 ATR(HTF)} × TP {3R, 5R, LIQ (HTF leg extreme, skip if < 2R)} ; max hold
2 days = **96**.

**C. Indices-focused OB (NAS100, US500, DAX).** TF {H1, H4} × def {BOS, BOS+FVG} × stars {any, ≥3} × D1 trend
{EMA20, EMA50} (mandatory) × entry {proximal, mid} × TP {2R, 3R, LIQ ≥1.5R} × max hold {1d, 2d} = **192**.
SL = distal − 0.2 ATR(TF).

**D. Trade management** on the overall best family winner (highest TRAIN t among the A/B/C winners):
M0 none (= winner), M1 break-even at +1R (SL → entry from the M1 bar after +1R is touched), M2 50% partial at +1R
(limit, trade-through) + BE on the rest, M3 structure trail (after +1R, SL = max(SL, lowest low of last 3 closed bars of
the zone TF; LTF for family B)). **+3** configs.

**E. Max-3h variant** of the same best family: its grid rerun with max hold = 3h instead of the hold dimension, selected
on TRAIN with the same rule (A: 96, B: 96, C: 96 configs; only the best family's grid is run).

Total K ≈ 192 + 96 + 192 + 3 + 96 = **579** → Bonferroni two-sided 5% bar on TRAIN t ≈ **|t| > 3.9**.

## 5. Ranking (frozen) and verdict
* Eligible: TRAIN n ≥ 100 and ≥ 0.25 trades/week (fallback n ≥ 50 if nothing qualifies, flagged).
* Score = **TRAIN t-stat of mean net R** (1× costs incl. swap). Winner per family = max score. TEST read once.
* **VIABLE** requires all: TEST mean net > 0 with 95% CI lower bound > 0; TEST mean net > 0 at 1.5× costs;
  ≥ 3 of 5 TEST calendar years (2022…2026) > 0; TEST mean net > random-baseline TEST mean net.
  **WEAK** = TEST mean net > 0 but fails another criterion. **FAIL** = TEST mean net ≤ 0.
* Random baseline: each winner trade replaced by 5 random trades (same symbol, random weekday minute within the same
  calendar month, random side, market entry, same risk as % of price, same TP in R (LIQ: the realised R target),
  same max hold).
* Metrics: n, trades/week, WR, avg R with 95% CI, PF, max DD (R), longest losing streak, avg hold, gross edge,
  per year / quarter, per asset group, 1.5× costs.
* Anything not listed here (other params, asset subsets, filters found after the fact) is exploratory and labelled so.
