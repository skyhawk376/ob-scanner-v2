# Backtest of OB Scanner v1 (research only: no deploy, no push, v1 untouched)

Generated 2026-10-06 at about 17:45 CEST (Europe/Paris), on branch `feat/always-on-fly`.
* **v1 = `/workspace/ob-scanner`**: the original prototype (repo `skyhawk376/ob-scanner`, first commit 2026-09-16, PythonAnywhere panel, port 8765). `PLAN.md` for v2 calls it "le prototype existant". v1's code, config, data and processes were **not modified**. Only a read-only copy was taken: `scripts/strategy_research/v1_backtest/v1_snapshot/` (app.js at v1 HEAD `58038f2`).
* **Scripts:** `scripts/strategy_research/v1_backtest/`
  * `v1_core.py`: numba port of v1's rules.
  * `parity_test.py`: compares the port with the original JS.
  * `run_v1.py`: zones, trades and random baseline.
  * `report.py`: builds the tables.
* **Outputs:** `data/backtest/strategy_research/v1_backtest/` (`summary.json`, `tables.md`, `trades_native_test.csv`, `parity_test.txt`; `trades_all_cost1.parquet` is local only because of the gitignore).

## TL;DR: v1 is not profitable after costs, in any version, group or timeframe
* **Native v1** (5★, entry at the zone edge, TP 2R), TEST 2022-01 → 2026-09:
  * 14,518 trades, about 59 per week.
  * **−0.359R per trade after costs, 95% CI [−0.388, −0.329].**
  * TRAIN 2015-2021 was −0.409R.
* **Before costs it is ≈ 0:** +0.024R (CI −0.000 / +0.048) on TEST and +0.029R on TRAIN.
  * That gross figure is only slightly better than random entries with the same SL, TP and hold (−0.010R).
  * Costs take **0.38R per trade**, because v1 zones are tiny: the median stop is 0.08% of price, about 1-4 pips on FX M5/M15.
* **The "user style" variants are worse:** mid-zone entry, TP 2R, 1h or 3h time stop give −0.65R net, ≈ 0 gross. Entering at the mid halves the stop, so costs double in R.
* **Every group, every TF, every symbol (15/15) and every year 2015-2026 is negative after costs.**
  * The least bad cell is native H1: −0.126R [−0.208, −0.044].
* **v1's own earlier result does not hold here.** Its backtest (`RAPPORT.md`: WR 45.9%, +91R) counted "fresh" with hindsight, skipped ambiguous bars and charged no costs. Here the gross WR is 33.7% against a 33.3% break-even at 2R.

## 1. v1 rules (from `app.js`, checked against the JS: `parity_test.txt`, 57 v1 cache files, 0 mismatches)
* **Universe and timeframes:**
  * 20 watchlist symbols: gold (PAXG and GC=F), NAS100, SP500, US30, RUSSELL, BTC, ETH, SOL, 9 FX pairs, silver and oil.
  * Timeframes M5, M15 and H1, on Yahoo and Coinbase data.
  * "Scan monde 5★" covers every symbol × TF and keeps **only 5★ OBs**.
* **Displacement candle:** a candle in the trade direction whose body is ≥ 1.5× the average body of the previous 20 candles, **or** whose close breaks the high/low of the previous 10 candles.
* **OB:** the last opposite-colour candle within the 8 bars before the displacement. The zone is that candle's full high-low. Only the first displacement per OB candle counts.
* **Stars (1 point each):**
  1. **FVG:** a 3-candle gap around the displacement (middle candle at disp−1, disp or disp+1), or a gap within the next 1-3 bars.
  2. **BOS:** the displacement close breaks the high/low of the prior 20 bars.
  3. **Sweep:** the low (or high) of the last 6 bars takes out the low (or high) of the 10 bars before them.
  4. **Fresh:** no later candle has **closed** through the zone's 50% line. Wicks into the zone are allowed.
  5. **P/D:** the zone mid is in the discount half (bull) or the premium half (bear) of a swing. The swing runs from the lowest low of the prior 50 bars to the highest high from the OB to disp+5.
     * Side effect: this rule favours shorts, which make 65% of the 5★ trades.
* **Trade shown by v1:**
  * Entry at the zone edge price reaches first: the high for a bull OB, the low for a bear OB. The code calls this the "far edge".
  * SL beyond the other edge, plus a buffer of max(7.5% of the zone height, 0.0015% of price).
  * TP at entry ± 2R.
  * No time stop, no trend filter, no session filter, no ATR.
* **Differences from v2 Filtre B:**

| | **v1** | **v2 Filtre B** |
|---|---|---|
| Timeframes | M5, M15, H1 | H1 only |
| Assets | 20 symbols, including indices and oil | Metals, forex and crypto |
| Stars | FVG / BOS-20 / sweep / fresh / P-D | FVG at creation / pivot trend / Fib 0.5 / no liquidity behind |
| Threshold | 5★ required | ≥ 4★ |
| Zone validity | "Fresh" = no close through the mid; touches allowed | Virgin (untouched) |
| Entry | Proximal edge | Mid of the zone |
| Stop | Distal edge + 7.5% of the zone | Distal edge + 0.05 ATR |
| Target | 2R | 2R |
| Time stop | None | 1h |

* **Causal replay (how alerts are timed in this backtest):**
  * v1 scores each OB with whatever candles exist at scan time. FVG looks ahead up to 3 bars and P/D up to 5 bars.
  * So each OB is re-scored on the closed candles available at each bar from disp to disp+5.
  * **The alert is the first closed bar where the OB scores 5★.** This assumes the user scans every bar close, which is the best case.
  * In TEST that gives 16,044 alerts: 10,283 on M5, 4,473 on M15 and 1,288 on H1.

## 2. Method (unchanged from `OB_FINAL_STRATEGY.md`, using its `ob_final/core.py` simulator and cost model)
* **Data:** M1 data from 2015 to 2026-09-30 (HistData/Dukascopy; crypto from Binance, starting 2017 or 2020).
  * 15 of v1's symbols are covered: XAU, XAG, NAS100, US500, BTC, ETH, SOL and 8 FX pairs. XAUUSD and XAUUSD_FUT both map to XAU.
  * **Missing (no long history on the box):** US30, RUSSELL, NZDUSD and OIL.
  * M5/M15/H1 bars are built from M1. The first 120 days are warm-up.
* **Execution:**
  * The limit order goes live **3 min after the alert bar closes**. A buy fills only when the ask trades through the level.
  * It stays valid for about v1's data window: 5 days on M5, 10 days on M15, 60 days on H1.
  * The simulation runs on the 1-minute path. When SL and TP fall in the same minute, the SL counts. On the fill minute, TP needs a close beyond it.
  * Native v1 has no time exit, so a safety cap closes every trade: 2 days on M5, 5 days on M15, 10 days on H1. Only 0.4% of trades hit it.
* **Costs:** spread, commission and slippage from `common.costs`, plus overnight swap (both sides pay).
  * "Gross" is a re-run at zero cost. A 1.5× cost run is also reported.
* **Split:** TRAIN = fills before 2022-01-01. TEST = fills from 2022-01-01 to 2026-09-30 (247.7 weeks).
* **Random baseline:** for each trade, a random weekday minute in the same symbol and month, a random side, market entry, the same stop as a % of price, TP 2R and the same max hold. 3 draws.
* **No optimisation:** 3 configs, fixed in advance.

## 3. Results (TEST 2022-01 → 2026-09 unless noted)

| Config | TEST trades | Trades/wk | WR (net) | Avg R gross | **Avg R net [95% CI]** | PF net | MaxDD R | Avg hold | Net @1.5× cost | TRAIN avg R net [95% CI] | Random TEST net / gross |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| **v1 native** (edge entry, TP 2R) | 14,518 | 58.6 | 29.2% | +0.024 | **−0.359 [−0.388, −0.329]** | 0.61 | 5,213 | 2.2 h | −0.541 | −0.409 [−0.432, −0.387] (n=17,906) | −0.447 / −0.010 |
| Variant mid entry, TP 2R, **1h** stop | 14,223 | 57.4 | 26.6% | +0.004 | **−0.652 [−0.685, −0.619]** | 0.40 | 9,276 | 0.2 h | −0.962 | −0.735 [−0.761, −0.710] | −0.766 / −0.002 |
| Variant mid entry, TP 2R, **3h** stop | 14,223 | 57.4 | 25.8% | +0.003 | **−0.653 [−0.686, −0.619]** | 0.42 | 9,282 | 0.3 h | −0.962 | −0.729 [−0.756, −0.703] | −0.778 / −0.013 |

**Reading the table:**
* MaxDD is the peak-to-trough fall of the cumulative R curve over all trades. The curve falls almost without a break.
* Holds are short because the stops are tiny. The median hold is 14 min for native and 4 min for the variants. 66% of native trades and 87% of variant trades are closed within 30 min.
* In the variants, only 8% (1h) and 3% (3h) of trades end on the time stop.

**Native v1, TEST, after costs, by group:**

| Group | n | Trades/wk | WR | Gross | Net [95% CI] | PF |
|---|---:|---:|---:|---:|---|---:|
| Indices | 2,051 | 8.3 | 27.4% | −0.001 | −0.198 [−0.268, −0.128] | 0.75 |
| Forex | 7,611 | 30.7 | 30.1% | +0.034 | −0.276 [−0.308, −0.243] | 0.67 |
| Metals | 1,672 | 6.8 | 23.6% | +0.028 | −0.470 [−0.537, −0.402] | 0.50 |
| Crypto | 3,184 | 12.9 | 31.2% | +0.013 | −0.603 [−0.695, −0.510] | 0.47 |

**Native v1, TEST, after costs, by timeframe:**

| TF | n | Trades/wk | WR | Gross | Net [95% CI] | PF | Avg hold |
|---|---:|---:|---:|---:|---|---:|---:|
| H1 | 1,177 | 4.8 | 31.0% | −0.033 | −0.126 [−0.208, −0.044] | 0.83 | 12.7 h |
| M15 | 3,984 | 16.1 | 31.5% | +0.034 | −0.176 [−0.221, −0.131] | 0.77 | 2.7 h |
| M5 | 9,357 | 37.8 | 28.0% | +0.027 | −0.466 [−0.506, −0.426] | 0.53 | 0.6 h |

**Group × TF, net R per trade (n):**

| | M5 | M15 | H1 |
|---|---|---|---|
| Metals | −0.562 (1,069) | −0.364 (481) | −0.079 (122) |
| Forex | −0.354 (4,870) | −0.142 (2,120) | −0.121 (621) |
| Indices | −0.228 (1,282) | −0.116 (566) | −0.234 (203) |
| Crypto | −0.816 (2,136) | −0.196 (817) | −0.071 (231) |

* **By year (native, net):** every year from 2015 to 2026 is between −0.29R and −0.49R.
* **By symbol (TEST):** all 15 symbols are negative, from NAS100 at −0.13R to BTC at −0.96R.

## 4. Verdict and caveats
* **Not profitable after costs.** The native v1 loses about 0.36R per trade out of sample, and the CI is far below 0. The 1h and 3h mid-entry variants lose about 0.65R.
* **Before costs, v1 is a coin flip at 2R.** Gross is +0.02R, about the same as random entries (−0.01R).
  * There is no meaningful selection edge to protect, and costs cannot be reduced enough to fix tiny-zone scalps.
  * Breaking even would need costs below about 1/16 of the modelled ones.
* **Caveats:**
  * **Data:** Dukascopy BID used as mid, and Binance spot as a proxy for crypto CFDs. v1's live feeds (PAXG, futures, Yahoo) differ slightly. 4 of the 19 unique v1 symbols could not be tested.
  * **Alert timing:** the replay assumes the user scans at every bar close. v1's Scan monde is manual, so real alerts would come later and be fewer.
  * **Same-bar fills:** when price is already inside the zone at alert time, the limit fills at the next open at a better price, with R still measured from the planned level. This is slightly favourable to v1.
  * **Native time cap:** v1 has no time exit, so a 2-, 5- or 10-day cap (by TF) was added only to close every trade. It binds on 0.4% of trades.
  * **Overlap:** trades can overlap. Trades/week counts every filled order.
  * **Costs** assume a good raw-spread account. Real manual execution is likely worse.

## Reproduce
```bash
cd scripts/strategy_research/v1_backtest
../../../.venv/bin/python parity_test.py /workspace/ob-scanner/cache   # Python port == v1 app.js (read-only)
NPROC=4 ../../../.venv/bin/python -W ignore run_v1.py all             # ~1 min, checkpoints in data/cache/strategy_research/v1_backtest/
../../../.venv/bin/python -W ignore report.py                         # summary.json, tables.md, trade list
```
