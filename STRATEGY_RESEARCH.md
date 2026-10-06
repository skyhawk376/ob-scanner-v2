# Intraday strategy research for manual Telegram alerts (research only, no deploy)

Generated 2026-10-06 ~11:30 CEST (Europe/Paris). Branch `feat/always-on-fly`. **Fly production untouched, nothing pushed.**
Scripts: `scripts/strategy_research/`. Outputs: `data/backtest/strategy_research/`. Pre-registration: `scripts/strategy_research/PREREGISTRATION.md` (committed 11:02 CEST, before any grid run).

## TL;DR: verdict

**No strategy survived.** None of the 248 pre-registered configurations (148 base + 100 "first fill of the day" variants, 5 families) is profitable after realistic costs, on TRAIN or on TEST. **0/148 base configs have a positive net average R in either period.** The OB 5★ / Filtre B logic is **negative after costs in every one of the 15 quarters** from 2023 to 2026 (≥4★, MFC, 1h, TP 1R).

* What is going on: most families have **little or no gross edge** at a 1h horizon (≈0 to +0.10R/trade before costs). Realistic costs for a manual trader cost **≈0.1–0.2R/trade** with ~1×ATR(H1) stops, and 0.3–0.8R with tight M15 stops. The cost model includes spread, commission and slippage on stop/market legs, plus a 3-minute alert→order delay.
* **No recommended strategy.** The pre-registered rule needed a family winner with TEST mean net R > 0. None qualified.
* **Best near-miss (by the frozen TRAIN ranking): OB ≥4★ + D1 EMA20 trend alignment, all 17 symbols, mid-limit entry, TP 1R, 1h time stop.** TRAIN −0.093R (n=352, gross +0.087R). **TEST −0.139R** [95% CI −0.281, +0.004], n=178, 0.55 trades/weekday, WR 46.6%, PF 0.73. Only 1 of 5 test quarters was positive. Do not trade it.
* **Only consistent gross edge found (diagnostic, not tradable):** the M15 FVG retest in the H4 trend during the US session (limit at the mid of the gap, stop just beyond the gap, TP 2R, excluding crypto). It made **+0.145R gross on TRAIN and +0.158R gross on TEST** (CI +0.02, +0.29). But the stops are so tight that costs take 0.2–0.8R per trade: **net −0.32R TRAIN / −0.17R TEST**. Widening the stop to cut costs also removes the edge (§6).
* The earlier "+0.10–0.21R/trade, WR ~56%" (6 weeks, 48 symbols, no costs) **does not replicate** on 3.75 years. On this data the realistic Filtre B equivalent is **−0.19R/trade (TP 1R) to −0.25R/trade (TP 2R) after costs** on TRAIN and TEST, and ≈0 gross. The "forex is best" finding also reverses: after costs, forex is the **worst** group, because costs are large relative to 1h moves.

## 1. Data (step 1: more data)

| Source | Assets | Period (UTC) | Resolution | Notes |
|---|---|---|---|---|
| **HistData.com** free M1 (verified identical to **Dukascopy BID M1**; EST no-DST → UTC) | XAUUSD, XAGUSD, EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD, USDCHF, EURJPY, GBPJPY, EURGBP, US500 (SPX CFD), NAS100, DAX | 2023-01-02 → 2026-09-30 | M1 (1.08–1.34 M bars/asset) | Checked against 15 Dukascopy day files (XAG, NAS100, USDJPY, Mar 2025): **100% identical OHLC at lag 0**, so the timezone conversion is correct. DAX 2023 has fewer bars (217 weekday gaps > 3h); metals and indices have ~80–95 gaps > 3h (holidays, maintenance). |
| **Binance spot** (data.binance.vision) | BTC, ETH, SOL (USDT) | 2023-01-01 → 2026-09-30 | M1 (1.97 M bars, no gaps) | Spot prices used as a proxy for CFD/perp. |
| Dukascopy datafeed (direct) | (all) | tried | M1 | Reachable but heavily rate-limited (HTTP 429, ~20 s per day file). Used only for the cross-check. |
| WTI (HistData) | dropped | — | — | Gap from 2024-01 to 2026-05. Energy is not covered. |
| yfinance H1 | not needed | — | — | M1 for everything is better than 730 days of H1. |

All bars are M1, so intrabar ordering is resolved at 1 minute. When SL and TP fall in the same minute, the SL counts. H1/H4/D1 bars are built from M1 (D1 = 17:00 New York roll; crypto = UTC day). Raw data is cached in `data/cache/strategy_research/` (gitignored). Inventory: `data_inventory.json`.

## 2. Execution and cost model (step 2)

* **Delay:** an alert becomes a live order **3 min after the signal bar closes**. Market orders fill at the open of that minute. Sensitivity checks use 1 and 5 min.
* **Limit fills need trade-through** by half the spread. **Stop and market legs pay the half-spread plus slippage.** Gaps fill at the worse open. TP on the fill bar counts only if the bar closes beyond it. Time stop = market exit at the close of the last minute of the hold.
* **Costs (1×):**

| Asset | Spread | Commission (round trip) | Slippage per stop/market leg |
|---|---|---|---|
| EURUSD / GBPUSD / USDJPY / AUDUSD | 0.2 / 0.4 / 0.3 / 0.3 pip | 0.6 pip | 0.2 pip |
| USDCAD, USDCHF, EURGBP / EURJPY / GBPJPY | 0.5 / 0.6 / 1.0 pip | 0.6 pip | 0.2 pip |
| XAUUSD / XAGUSD | $0.25 / $0.025 | $0.07 / $0.004 | $0.10 / $0.01 |
| US500 / NAS100 / DAX | 0.5 / 1.5 / 1.5 pt | 0 | 0.25 / 1 / 1 pt |
| BTC, ETH, SOL | 0.01% | 0.05% | 0.02% |

* **Simulator sanity check** (`random_baseline.py`: random side and minute, SL 1×ATR(H1), TP 1R, 1h). **Gross +0.013R TRAIN / −0.009R TEST** (≈0, as expected, so there is no hidden bias). **Net −0.123R / −0.114R.** That is the pure cost drag for a ~1 ATR(H1) stop: metals −0.19R, forex −0.10R, indices −0.11R, crypto −0.12R.

## 3. Method (steps 3–4)

* Split: **TRAIN = fills before 2025-07-01** (2.5 years, 651 weekdays). **TEST = 2025-07-01 → 2026-09-30** (15 months, 326 weekdays).
* Five pre-registered families with compact grids (details in PREREGISTRATION.md):
  * **A. OB 5★:** repo engine `detect_zones` unchanged. Causal walk-forward on H1, called at every bar with lookback 500 (2,971 zone records). Grid: score ≥4/≥5 × trend none/D1/H4 × TP 1R/2R × fill session × basket = 48.
  * **B. Session liquidity sweep reversal:** Asian or day range swept at the London or NY window, then an M5 reclaim (12 configs).
  * **C. Opening-range breakout:** 08:00 / 09:00 Paris, 09:30 New York; 15/30-min range (48 configs).
  * **D. M15 FVG retest in trend:** EU or US window (32 configs).
  * **E. Baseline:** previous-day high/low fade or breakout (8 configs).
* Hold time: **60 min after the fill** for ranking. 120 and 240 min are reported for information only.
* **Ranking (pre-registered):** eligible if TRAIN n ≥ 150 and 0.5–3 trades/weekday; score = TRAIN t-stat of mean net R; winner = best per family. Configs above 2 trades/weekday also enter as a "first fill of the day" variant, so K = 248 and the Bonferroni bar is |t| > 3.72.

## 4. Results across ALL configs (net = after 1× costs; gross = zero cost)

| Family | Configs | Net > 0 on TRAIN | Net > 0 on TEST | Best TRAIN net | Median TRAIN / TEST net | Best TRAIN gross | Median TRAIN / TEST gross | Gross > 0 in both |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A OB 5★ | 48 | 0 | 0 | −0.087 | −0.165 / −0.286 | +0.098 | +0.025 / −0.126 | 3 |
| B Sweep reversal | 12 | 0 | 0 | −0.298 | −0.368 / −0.366 | +0.069 | +0.010 / +0.031 | 5 |
| C ORB | 48 | 0 | 0 | −0.105 | −0.275 / −0.248 | +0.059 | 0.000 / −0.018 | 12 |
| D FVG retest | 32 | 0 | 0 | −0.112 | −0.211 / −0.184 | +0.104 | −0.018 / +0.012 | 7 |
| E Prev-day H/L | 8 | 0 | 0 | −0.125 | −0.167 / −0.138 | +0.004 | −0.042 / −0.022 | 1 |

Full per-config tables (TRAIN, TEST, gross): `grid_full_<family>.csv`.

## 5. Family winners (selected on TRAIN, frozen) on TEST, after costs

| Winner (TRAIN-selected) | TRAIN n / avg R (t) | TEST n | /wd | WR | **TEST avg R [95% CI]** | PF | Max DD R | Longest losing streak | 1.5× / 2× cost | Delay 1 / 5 min | Hold 2h / 4h (TEST) | Test quarters > 0 |
|---|---|---:|---:|---:|---|---:|---:|---:|---|---|---|---:|
| A OB ≥4★, D1 EMA20 aligned, ALL 17, TP 1R | 352 / −0.093 (−1.70) | 178 | 0.55 | 46.6% | **−0.139** [−0.281, +0.004] | 0.73 | 35.3 | 11 | −0.257 / −0.357 | −0.133 / −0.139 | −0.077 / −0.068 | 1/5 |
| E PDH/PDL fade, EU 08–12h, TP 2R, first fill/day | 577 / −0.086 (−2.31) | 298 | 0.91 | 38.9% | **−0.208** [−0.296, −0.121] | 0.52 | 64.4 | 8 | −0.274 / −0.335 | −0.208 / −0.208 | −0.210 / −0.266 | 0/5 |
| B Sweep LON, market entry, TP 2R, first fill/day | 647 / −0.947 (−2.74) | 323 | 0.99 | 30.7% | **−0.397** [−0.535, −0.259] | 0.51 | 130.1 | 13 | −0.571 / −0.647 | −0.351 / −0.558 | −0.386 / −0.418 | 0/5 |
| D FVG EU, H1 trend, proximal, SL first candle, TP 2R, first fill/day | 632 / −0.121 (−2.87) | 311 | 0.95 | 40.5% | **−0.100** [−0.214, +0.015] | 0.79 | 37.2 | 10 | −0.166 / −0.275 | −0.079 / −0.059 | −0.088 / −0.073 | 0/5 |
| C ORB EU 09:00, 30 min, SL opposite, TP 2R, D1 filter, first fill/day | 641 / −0.329 (−8.87) | 324 | 0.99 | 33.0% | **−0.364** [−0.462, −0.265] | 0.39 | 117.9 | 9 | −0.466 / −0.588 | −0.313 / −0.385 | −0.352 / −0.355 | 0/5 |

Gross (zero-cost) TRAIN / TEST for the winners: A +0.087 / +0.022, E +0.023 / −0.076, B −0.039 / +0.030, D +0.043 / −0.009, C −0.173 / −0.194. Other top-10 TRAIN configs on TEST: everything negative. The least-bad was D FVG US / H4 / proximal / first fill/day at −0.021 [−0.139, +0.096]. It was not a family winner. Selecting it now would be choosing on TEST.

**Near-miss detail (A: OB ≥4★ + D1 alignment, TP 1R, 1h):**

* TRAIN by year: 2023 −0.055 (n=145), 2024 −0.125 (148), 2025 H1 −0.107 (59).
* TEST by quarter: 2025Q3 −0.01, 2025Q4 +0.13, 2026Q1 −0.14, 2026Q2 −0.42, 2026Q3 −0.31.
* By group, TRAIN / TEST:

| Group | TRAIN | TEST |
|---|---|---|
| Indices | +0.137 (n=76) | +0.041 (n=29) |
| Crypto | −0.083 | +0.036 |
| Metals | −0.502 (n=33) | +0.045 (n=12) |
| Forex | −0.120 (n=177) | −0.274 (n=101) |

Every group subset is small, and picking "indices only" would be data-mining. Exact rules, in case someone wants to paper-trade it as a hypothesis:

* **Zone:** the scanner's H1 OB with ≥4★ (virgin, FVG required). Take it only if the last closed D1 bar closes above its EMA20 for a bull zone, or below for a bear zone.
* **Entry:** limit at the engine entry (mid of the zone if the height is above 1 ATR, otherwise the OB open), live 3 min after the alert, valid 24h.
* **Exit:** SL at the engine stop (distal edge + 0.05 ATR). TP +1R. Close at market 60 min after the fill.

**Not recommended for real money.**

**Old findings re-tested on 3.75 years** (≥4★ MFC = current Filtre B, 1h, any session):

| Variant | TRAIN net | TEST net | Gross TRAIN / TEST |
|---|---|---|---|
| TP 1R | −0.189 [−0.265, −0.112], n=540 | −0.218 [−0.324, −0.112], n=286 | −0.004 / −0.035 |
| TP 2R | −0.247, n=540 | −0.252, n=286 | — |
| + D1 alignment | −0.157 | −0.173 | +0.025 / +0.012 |
| 5★ only | −0.104 (n=139) | −0.249 (n=70) | — |

TP 1R is net-negative in all 15 quarters. Over the last 6 weeks (2026-08-20 → 09-30; 14 MFC symbols here versus 48 before) the same rules give n=28 at −0.40R net / −0.14R gross. The earlier positive 6-week figure is well within the noise of samples that size.

## 6. Exploratory checks (NOT pre-registered; cannot count as evidence)

| Idea | TRAIN gross / net | TEST gross / net [95% CI] | Comment |
|---|---|---|---|
| X1 US-index intraday momentum: at 15:30 NY (21:30 Paris) take the sign of the first half-hour return, exit at 16:00 NY (US500 + NAS100) | +0.045 / −0.035 (n=1040) | −0.037 / −0.090 [−0.13, −0.05] (n=599) | The literature effect is not there net, nor gross on TEST |
| X1 variant: sign of the 09:30→15:30 return | −0.040 / −0.116 | −0.037 / −0.090 | Negative |
| X2 FVG US / H4 / mid / gap stop / TP 2R, non-crypto (XAU, XAG, EURUSD, USDCAD, NAS100, US500) | **+0.145** / −0.323 (n≈1,200) | **+0.158** / −0.171 [−0.31, −0.04] (n≈690) | Real-looking gross edge in both periods; costs ≈0.2–0.8R per trade |
| X2 with stop floored at 0.5×ATR(H1) | +0.058 / −0.141 | +0.088 / −0.073 [−0.17, +0.03] | Wider stop dilutes the edge faster than it cuts costs |
| X2 with stop floored at 1.0×ATR(H1) | +0.015 / −0.082 | +0.029 / −0.046 [−0.12, +0.03] | ≈0 gross |

The X2 gross edge appears in both periods and in 6 of 6 non-crypto symbols on TEST. At 0.5× costs it is ≈0 (TRAIN −0.110, TEST −0.004). At **0.3× costs** it is TRAIN +0.005 and TEST +0.050 [−0.09, +0.19]. In other words it only reaches breakeven at about **a third of realistic costs**. That is not realistic for manual execution from Telegram alerts. It is a lead for automated, low-cost execution, not for this use case.

## 7. Caveats and what is NOT proven

* **Costs are assumptions** for a good raw-spread/ECN account. At **0.5× costs** (`cost_half_sensitivity.json`) the winners score as follows on TRAIN / TEST: A OB+D1 +0.011 / −0.063, D FVG EU −0.059 / −0.017, E −0.036 / −0.157, B −0.249 / −0.262, C −0.246 / −0.275. So even at half the costs, nothing is clearly positive. Real manual execution (news spikes, rollover spreads, partial fills) is likely **worse** than modelled.
* **Data:** Dukascopy BID quotes are treated as mid. The half-spread error cancels on average between longs and shorts. Index and metal CFD prices are Dukascopy's, not your broker's. Crypto uses Binance spot.
* **Multiple testing:** K = 248. Even the best TRAIN t-stat (−1.70) is negative, so no deflation is needed to reject. A positive result would have needed |t| > 3.7.
* **Grids were deliberately compact.** Untested: other session windows, partial exits / break-even management (the earlier BE@+1R idea), news filters, swing horizons (> 4h), and other assets (energy, minor crosses). A wider search on this data would very likely find something positive on TRAIN by chance. TEST results here show how that usually ends.
* **The 1h maximum hold is the binding constraint.** Gross edges at 1h are tiny compared with the cost of a round trip. The 2h and 4h holds (info only) did not rescue any winner.

## 8. Practical recommendation

1. **Do not add a new alert type to production on the basis of this research.** No candidate cleared even the weak bar of TEST mean > 0.
2. The live Filtre B alerts should be presented as **unproven / negative expectancy after costs** on 3.75 years. If they stay on, paper-trade them with real fills before risking money.
3. If you continue research, the evidence points away from 1h manual scalping. Better directions are longer holds with wider stops (costs < 0.05R), or automated low-cost execution of the M15 FVG/H4-trend idea. Any of these needs a new pre-registration and a fresh hold-out.

## Reproduce

```bash
.venv/bin/python scripts/strategy_research/fetch_histdata.py 2023 2026 9   # FX/metals/indices M1
.venv/bin/python scripts/strategy_research/fetch_binance.py 2023-01 2026-09 BTC ETH SOL
.venv/bin/python scripts/strategy_research/data_check.py
.venv/bin/python scripts/strategy_research/ob_detect.py                    # ~5 min on 6 cores
.venv/bin/python scripts/strategy_research/run_grid.py A_OB B_SWEEP C_ORB D_FVG E_PDHL
COST=0 .venv/bin/python scripts/strategy_research/run_grid.py A_OB B_SWEEP C_ORB D_FVG E_PDHL
.venv/bin/python scripts/strategy_research/select_eval.py
.venv/bin/python scripts/strategy_research/summarize.py
.venv/bin/python scripts/strategy_research/random_baseline.py
.venv/bin/python scripts/strategy_research/exploratory.py
```
Requires `numba` and `scipy` in `.venv` (installed locally for this research; `requirements.txt` was not changed).
