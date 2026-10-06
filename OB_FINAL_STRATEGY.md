# OB-only final study: HTF swing, HTF zone + LTF CHoCH, indices, management, ≤3h (research only: no deploy, no push)

Generated 2026-10-06, about 17:30 CEST (Europe/Paris), on branch `feat/always-on-fly`. Fly is untouched and nothing was pushed.
* **Pre-registration:** `scripts/strategy_research/PREREG_OB_FINAL.md`, committed at **17:08 CEST (commit 849d71e), before any backtest**.
* **Scripts:** `scripts/strategy_research/ob_final/`.
* **Outputs:** `data/backtest/strategy_research/ob_final/`.
* **Scope:** order blocks only ("juste les OBs").

## TL;DR: no OB strategy is profitable after costs

* **0 of 579 pre-registered configs** pass. To pass, a config needed TEST > 0 with the 95% CI above 0, TEST > 0 at 1.5× costs, ≥ 3/5 positive TEST years, and a result better than random entries.
  * **The best TRAIN t-stat in the whole study is +1.54.** The multiple-testing bar is |t| > 3.9.
  * **Not one config** has a TRAIN t above 2, even before any deflation for multiple testing.
* **Every pre-registered family winner** (selected on TRAIN 2015-2021, read once on TEST 2022-2026/09) is **≈ 0 or negative on TEST after costs**:

| Rank (TEST net) | Family (frozen TRAIN winner) | TRAIN n / net R (t) | TEST n | Trades/wk | WR | **TEST net R [95% CI]** | PF | MaxDD R | Losing streak | Avg hold | TEST gross | TEST at 1.5× cost | TEST years > 0 | Random-entry TEST | Verdict |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | **E (≤3h) of best family A**: D1 OB, BOS, any ★, D1 EMA50 aligned, limit at proximal edge, TP = leg extreme (≥1.5R), **max 3h** | 349 / +0.155 (1.54) | 316 | 1.28 | 52.9% | **+0.011 [−0.034, +0.056]** | 1.08 | 6.2 | 8 | 2.9 h | +0.034 | +0.003 | 3/5 | −0.027 | WEAK (≈ 0) |
| 2 | D3: A winner + structure trail after +1R | 349 / +0.106 (0.96) | 316 | 1.28 | — | −0.012 [−0.126, +0.102] | 0.97 | 18.6 | — | 79 h | +0.028 | −0.027 | 1/5 | — | FAIL |
| 3 | **C (indices)**: H4 OB + FVG, ≥3★, D1 EMA50, proximal, TP 2R, max 2d | 129 / +0.104 (0.74) | 99 | 0.40 | 35.4% | **−0.003 [−0.268, +0.263]** | 1.00 | 26.1 | 16 | 14.6 h | +0.080 | −0.015 | 3/5 | −0.010 | FAIL |
| 4 | D2: A winner + 50% partial at +1R + BE | 349 / +0.119 (1.10) | 316 | 1.28 | — | −0.024 [−0.125, +0.076] | 0.94 | 15.7 | — | 80 h | +0.016 | −0.039 | 1/5 | — | FAIL |
| 5 | D1: A winner + break-even at +1R | 349 / +0.100 (0.89) | 316 | 1.28 | — | −0.031 [−0.144, +0.082] | 0.93 | 21.3 | — | 80 h | +0.009 | −0.046 | 1/5 | — | FAIL |
| 6 | **A (HTF swing, 17 assets)**: D1 OB, BOS, any ★, D1 EMA50, proximal, TP = leg extreme, max 5d | 349 / +0.090 (0.79) | 316 | 1.28 | 41.8% | **−0.044 [−0.163, +0.074]** | 0.91 | 22.9 | 10 | 84 h | −0.006 | −0.060 | 1/5 | −0.042 | FAIL |
| 7 | **B (HTF zone + LTF CHoCH)**: D1 zone ≥3★, M5 CHoCH, SL beyond the zone, TP 5R, max 2d | 221 / −0.035 (−0.64) | 198 | 0.80 | 45.0% | **−0.049 [−0.172, +0.075]** | 0.86 | 18.4 | 7 | 32 h | −0.020 | −0.062 | 1/5 | −0.019 | FAIL |

* **Notes on the table:**
  * **Net** = after spread, commission, slippage and swap. **Gross** = the same rules re-simulated at zero cost.
  * **Random-entry TEST** = the pre-registered random baseline (same symbol and month, random side, same risk %, same TP in R, same max hold), after costs.
  * **Trades/wk** = across all assets of the family.
* **Best near-miss: the ≤3h D1-OB variant (row 1).** It is positive on TEST, but only by **+0.011R per trade** with a CI of ±0.045R, i.e. indistinguishable from zero.
  * Its TRAIN edge comes almost entirely from **2020 (COVID, +1.01R/trade on 50 trades)**. The other TRAIN years are ≈ 0.
  * The recent slice (2025-07 → 2026-09) is −0.002R.
  * **Do not trade it.** Rules are in §5 only so you can paper-trade it.
* **Management (family D)** reduces drawdown, but every variant stays negative on TEST.
* **LTF confirmation (family B) is the worst family:** **0 of 96** configs are positive on TRAIN, and its ≤3h version has 0/96 positive on TRAIN or TEST.
* **The earlier indices near-miss does not hold on longer history.** That was H1 OB ≥4★ + D1 trend on indices, +0.137R TRAIN / +0.041R TEST on 2023-26.
  * On 2015-2021, **0 of 96** H1 index configs (family C) are positive after costs (mean −0.16R).
  * The only weak, recurring pattern is **H4** index OBs with D1 trend in **2022-2026** (§4). It is flat on 2015-2021, so it is not a stable edge.

## 1. Data
* **Sources:**
  * HistData (= Dukascopy BID) M1, extended back to **2015-01** for 11 FX pairs, XAU, XAG, US500, NAS100 and DAX.
  * Binance spot M1 from **2017-08** for BTC and ETH, and **2020-08** for SOL.
  * Everything runs to 2026-09-30. Inventory: `data_inventory.csv`.
* **Volume:** 2.9 to 4.8 M M1 bars per asset.
* **DAX** has many more gaps (2,137 gaps over 3h). Its early-years file covers fewer hours.
* **Split:** TRAIN = fills before 2022-01-01. TEST = fills from 2022-01-01 to 2026-09-30.
  * The first 120 days of each asset are warm-up only.
  * The RECENT slice (2025-07-01 onward, the old studies' test) is reported for information only.
* The extended files are saved as `*_M1_2015_2022.parquet` / `*_M1_2017_2022.parquet`. The framework's own files were **not overwritten**.

## 2. Method (frozen in the prereg)
* **Execution:** framework conventions.
  * The order goes live 3 min after the signal bar closes.
  * A limit fills only when price trades through by half the spread.
  * Stop and market legs pay half the spread plus slippage.
  * When SL and TP fall in the same minute, the SL counts (1-min path).
  * On the fill bar, TP counts only on a close beyond it.
* **Simulator check:** the two-stage numba simulator in `ob_final/core.py` reproduces `common._sim` **exactly** on 3 × 3,000 random orders (EURUSD/XAU/BTC: same fills, same exits, max |ΔR| = 0; `selftest.txt`).
* **Costs:** `common.costs` (unchanged), plus **swap** per calendar day held, charged on both sides (conservative):
  * FX 1.5% / 1.5% a year.
  * Metals 7.3% long / 3.65% short.
  * Indices 6% / 2%.
  * Crypto 10% / 3%.
* **OB definition ("OBX", broad):**
  * A BOS is a close beyond the last confirmed fractal pivot (n=3 for H1/H4, n=2 for D1).
  * The OB is the last opposite-colour candle at or before the leg extreme. The zone is its full high/low.
  * Variants: BOS only, or BOS + FVG in the leg. Virgin rule as in the engine (no touch from OB+3 to confirmation). First touch only.
  * A star score ★1-★4 (FVG, pivot trend, Fib discount, no untaken liquidity behind) is used **as a filter** (any vs ≥3).
  * One zone per OB candle.
* **Families:**
  * **A:** H4/D1 swing, 17 assets, holds 5/10 days. 192 configs.
  * **B:** H4/D1 zone tap, then an M5/M15 CHoCH within 24/48h; market entry; SL at the LTF swing or beyond the zone; TP 3R/5R/leg extreme; max 2 days. 96 configs.
  * **C:** indices H1/H4, D1 EMA20/50 trend required, holds 1/2 days. 192 configs.
  * **D:** management on the best TRAIN family winner (A). 3 configs.
  * **E:** the best family's grid with max hold 3h. 96 configs.
  * **K = 579.**
* **Ranking:**
  * Eligible if TRAIN n ≥ 100 and ≥ 0.25 trades/week. Every family had eligible configs, so no fallback was used.
  * Score = TRAIN t-stat of net R. Best family = highest TRAIN t among the A/B/C winners: A (0.79) vs C (0.74) vs B (−0.64).

## 3. Whole grids (not only winners)

| Family | Configs | Net > 0 TRAIN | Net > 0 TEST | Both > 0 | TEST CI lower > 0 | Gross > 0 in both | Median net TRAIN / TEST | Median gross TRAIN / TEST | Best TRAIN t | TRAIN top-10 positive on TEST |
|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| A HTF swing | 192 | 27 | 16 | **0** | 0 | 58 | −0.076 / −0.083 | +0.022 / −0.008 | 0.79 | 0/10 |
| B HTF + LTF CHoCH | 96 | **0** | 13 | 0 | 0 | 1 | −0.161 / −0.054 | −0.067 / +0.009 | −0.64 | 0/10 |
| C indices | 192 | 38 | 90 | 31 | 3 | 118 | −0.102 / −0.004 | +0.058 / +0.065 | 0.74 | 8/10 |
| E-A (≤3h, prereg) | 96 | 24 | 25 | 6 | 0 | 47 | −0.051 / −0.042 | +0.037 / +0.013 | 1.54 | 2/10 |
| E-B (≤3h, info) | 96 | 0 | 0 | 0 | 0 | 4 | −0.118 / −0.070 | −0.030 / −0.012 | −1.48 | 0/10 |
| E-C (≤3h, info) | 96 | 26 | 58 | 26 | 5 | 69 | −0.116 / +0.030 | +0.036 / +0.092 | 1.41 | 10/10 |

Full tables: `grid_<fam>.csv`, `top10_<fam>.csv`, `winners_detail.json` (per year, per quarter, per group, per symbol, by side, exit reasons, baselines).

**Gross edge:** before costs the HTF OBs are ≈ 0, with medians of −0.07 to +0.06R. Costs at these horizons are small: about 0.02-0.08R per trade, including swap. **The problem is no longer costs, it is the absence of edge.** Random entries with the same stops, targets and holds score about the same, between −0.04R and +0.03R net.

## 4. The only recurring pattern: index H4 OBs with D1 trend in 2022-2026 (exploratory, not evidence)
* The 96 C configs on **H4**:
  * **76/96 are positive on TEST** (mean +0.099R), but only 38/96 on TRAIN (mean −0.019R).
  * Only 3/96 have a TEST CI above 0.
* **The frozen C winner is the weakest kind of signal:**
  * TEST −0.003R.
  * By side, TRAIN longs +0.24 / shorts −0.15, then TEST longs −0.16 / shorts +0.24. The sign flips between periods.
  * Bootstrap P(TEST mean ≤ 0) = 0.51.
* **Exploratory checks on the same rules applied elsewhere:**
  * Metals: negative (TRAIN −0.35, TEST −0.23).
  * FX: negative (−0.21 / −0.17).
  * Crypto: positive (+0.27 / +0.23, n = 50 / 99). This is a post-hoc observation only.
* **Verdict:** this is a 2022-26 index regime, not an OB edge. Do not select it. Selecting it now would mean choosing on TEST.

## 5. Best near-miss (paper-trade only; NOT recommended): "D1 OB first touch, 3h scalp"
These rules are exact and could be turned into Telegram alerts:
1. **Universe:** the 17 assets (11 FX, XAU, XAG, US500, NAS100, DAX, BTC, ETH, SOL).
2. **Scan time:** once a day at the D1 close (17:00 New York = 23:00 Paris; crypto 00:00 UTC).
3. **Zone (bull; bear is the mirror):**
   1. The D1 close is above the most recent confirmed D1 fractal pivot high (2 bars each side). That pivot is used only once.
   2. Leg low = the lowest low between that pivot and the breakout bar.
   3. **OB = the last bearish D1 candle at or before the leg low** (≤ 10 bars back). Zone = that candle's high/low.
   4. The zone is valid only if no D1 bar from OB+3 to the breakout bar has touched it. Only one alert per OB candle.
4. **Filter:** the last closed D1 close is above the D1 EMA50 (below it for bear).
5. **Alert (3 min after the D1 close):**
   * **BUY LIMIT** at the zone high (proximal edge).
   * **SL** = zone low − 0.2 × ATR14(D1).
   * **TP** = the leg extreme: the highest high since the leg low, updated until the fill. Skip the trade if TP is < 1.5R from entry at the fill.
   * The order is valid 40 days and is cancelled after the first touch.
6. **Exit:** **close at market 3h after the fill** if neither SL nor TP was hit. In TEST, 95% of trades ended on this time stop.
7. **Performance (TEST 2022-01 → 2026-09, after costs):**
   * 316 trades, 1.28 per week across 17 assets, WR 52.9%, avg hold 2.9h.
   * **+0.011R/trade** [−0.034, +0.056], PF 1.08, max DD 6.2R, longest losing streak 8.
   * 1.5× costs: +0.003R. Gross: +0.034R.
   * TEST years 2022-26: +0.00 / +0.06 / −0.01 / +0.05 / −0.05R.
   * RECENT slice: −0.002R.
   * Because the stop is a full D1 zone and the exit comes after 3h, each trade moves only a small fraction of R. **Economically ≈ 0.**

**User-requested ≤3h version of the best family:** this *is* the pre-registered E variant of family A, shown above.
* Info only (not pre-registered as a selection): the ≤3h winner of the indices family C makes **+0.014R** on TEST [−0.14, +0.16].
* The C winner's own rules with a 3h cap make +0.043R [−0.11, +0.19].
* Both are noise.

## 6. Trade management (family D, on the A winner)
* **Results:** none / BE +1R / 50% partial +1R + BE / structure trail.
  * TEST net: −0.044 / −0.031 / −0.024 / −0.012R.
  * Max DD: 22.9 / 21.3 / 15.7 / 18.6R.
* Management trims losses slightly and cuts drawdown, but turns nothing positive. Every variant has only 1/5 positive TEST years.
* **Exploratory, on the C winner:** management made TEST worse (−0.065 to −0.019R vs −0.003R).

## 7. Robustness verdict and caveats
* **Verdict: nothing survives. The honest answer to "a profitable OB strategy after costs" is: not found, on 11.75 years × 17 assets with a pre-registered, compact search.**
  * This covers intraday (previous studies), HTF swing, HTF + LTF confirmation, indices-focused, management and ≤3h.
  * Every OB family is ≈ 0 before costs and ≤ 0 after costs, out of sample.
* **Deviation (bug fix, reported in full):** the first full run counted **duplicate zones**. 534 of 16,272 zones (3.3%) came from a later BOS re-using the same OB candle, which double-counted one order.
  * I found this during sanity checks after the first evaluation. I fixed it to "one zone per OB candle, keep the first", which is rule-neutral, then re-ran everything.
  * **Before the fix, the frozen C winner was a different config:** H4/FVG/≥3★/EMA50/**mid/3R/1d**, at **TEST +0.261R [−0.08, +0.60]** (WEAK).
  * **After the fix,** that same config is +0.183 [−0.16, +0.53] (n=94). It is no longer the TRAIN winner, and the new winner is −0.003R.
  * A 3% data change flipping the "best" config is itself strong evidence of noise. Old files: `selection_v0_with_dup_zones.json`, `evaluate_v0_with_dup_zones.log`.
* **Costs and data:**
  * Costs are assumptions for a good raw-spread account. Index spreads overnight and around news are wider than the fixed spreads used. The swap model is a flat approximation.
  * Prices are Dukascopy BID used as mid, Binance spot used as a CFD proxy, and the DAX early-years file has gaps.
* **Overlapping positions:** zones are independent, so several positions on one asset can overlap. Trades/week counts every filled order.
* **Not tested** (would need a new pre-registration and a fresh hold-out):
  * W1 zones.
  * Discretionary "Kasper-style" hand-drawn OBs.
  * News filters.
  * Session-specific spreads.
  * Futures data.

## Reproduce
```bash
.venv/bin/python scripts/strategy_research/ob_final/fetch_long.py histdata && .venv/bin/python scripts/strategy_research/ob_final/fetch_long.py binance
cd scripts/strategy_research/ob_final
../../../.venv/bin/python selftest.py                       # simulator == common._sim
NPROC=3 ../../../.venv/bin/python run_asset.py all          # ~2.5 min, checkpoint per asset (data/cache/.../ob_final/trades/)
../../../.venv/bin/python grid.py A B C EA EB EC            # grids + TRAIN selection
../../../.venv/bin/python evaluate.py                       # TEST, 1.5x, gross, baselines, family D
../../../.venv/bin/python explore.py && ../../../.venv/bin/python dump.py   # exploratory + trade lists + inventory
```
