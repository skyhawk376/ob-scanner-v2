# OB 5★ on XAUUSD only, multi-timeframe (M5 → W): research only, no deploy, no push

Generated 2026-10-06 ~15:30 CEST (Europe/Paris), branch `feat/always-on-fly`.
Pre-registration: `scripts/strategy_research/PREREG_OB_XAU.md`, committed at 14:57 CEST (commit fa77329) **before any backtest
result**. Script: `scripts/strategy_research/ob_xau_multitf.py`. Outputs: `data/backtest/strategy_research/ob_xau/`.

## TL;DR: nothing works

* **No timeframe is viable.** All 6,480 pre-registered configs were checked (M5, M15, M30, H1, H4, D1, W, plus the "HTF zone + London/NY touch" mix).
  * The TRAIN-selected best config of every testable TF loses money on TEST after costs: M5 −0.36R, M15 −0.13R, M30 −0.55R, H1 −0.28R per trade.
  * The best TRAIN t-stat in the whole grid is **+0.73**. The multiple-testing bar is |t| > 4.47.
  * **0 of 4 testable winners** are positive on TEST.
* **Before costs, OBs on XAU have ≈ no edge** at every TF. Plain ≥3★ engine zones, mid entry, TP 2R, 1h:

| TF | Gross TRAIN | Gross TEST | Gross PRE-SAMPLE 2020-22 |
|---|---:|---:|---:|
| M5 | −0.05 | +0.09 | +0.03 |
| M15 | −0.18 | −0.11 | +0.03 |
| M30 | +0.01 | +0.11 | +0.02 |
| H1 | −0.13 | −0.15 | −0.05 |

  Costs then remove ≈0.1–0.65R per trade on M5–M30 (median cost/risk 0.38 on M5 and 0.21 on M15 in TRAIN).
* **HTF (H4 / D1 / W, Kasper style) cannot even be tested with the scanner's 5★ engine on gold.**
  * The virgin + FVG + star rules plus "first touch" give only these TRAIN fills in 2.5 years: **9** (H4 ≥3★), **4** (D1), **1** (W).
  * The H4/D1 "London/NY touch, hold ≤ 3h" mix gives **7** (H4) and **3** (D1).
  * No config reaches n ≥ 20, so there is no verdict.
  * A looser **exploratory** version (any virgin engine OB, FVG optional) gets more trades: H4 ~0.08/weekday, D1 ~0.03/weekday. It is still ≈0 gross and negative net on TEST (H4 −0.19R, D1 −0.07R).
* **Frequency.** On XAU alone, the only config near the wanted ~1 trade/day is **M5 ≥3★**: 1.1 per weekday, **−0.69R net on TRAIN, −0.10R on TEST**. Everything else is 0.03–0.4 per weekday.

## 1. Setup (frozen in the prereg)

* **Data:** XAUUSD M1 from HistData (= Dukascopy BID). Framework file 2023-01-02 → 2026-09-30, plus 2019-2022 from the same source.
  The extra years are used only for detection warm-up (D1/W need context) and as a supplementary **PRE-SAMPLE** hold-out (2020-2022). They were never used for selection.
* **Split:** **TRAIN** = fills 2023-01-02 → 2025-06-30 (651 weekdays). **TEST** = 2025-07-01 → 2026-09-30 (326 weekdays).
* **Execution:** the framework simulator core `common._sim` is used unchanged:
  * The order is live 3 min after the signal bar closes.
  * A limit fills only on trade-through by half the spread.
  * SL wins when SL and TP fall in the same minute. On the fill bar, TP counts only on a close beyond it.
* **Costs (XAU):** spread $0.25, commission $0.07, slippage $0.10 per stop or market leg.
  * **Swap** (new, because holds go up to 4 weeks): long 0.020% and short 0.010% of price per rollover (Wednesday ×3). Both sides are charged.
* **Detection:** repo engine `detect_zones` unchanged, causal walk-forward at every bar (closed bars only).
  * Params: M5/M15/M30 pivot 3 / lookback 300; H1 and H4 `params_for_tf` (3/500); D1 2/400; W 2/260.
  * The H1 detection reproduces the earlier study's XAU zones exactly: 127/127 4★ and 33/33 5★, with identical detection times.
  * **H4/D1/W ★5:** the engine leaves it pending until touch, so ★5 = the first touch falls in London 08:00–11:30 or NY 14:30–17:30 Paris.
* **Grid per TF:**
  * stars ≥3/4/5;
  * entry mid (engine) / proximal;
  * SL engine distal +0.05 ATR / +0.10 ATR;
  * TP 1/2/3R;
  * holds 1/2/3h, plus H4 24/48h, D1 3/5d, W 14/28d;
  * trend none / H4 EMA50 / D1 EMA50 aligned;
  * session all / London+NY.
  * Limit validity: M5 2h, M15 6h, M30 12h, H1 24h, H4 4d, D1 28d, W 84d.
* **MIX:** H4 or D1 zone. Alert when price first reaches the zone during London/NY. Entry is market or a limit at mid. Hold 1–3h.
* **K = 6,480 configs** (648 per TF for M5–H1, 1,080 for H4/D1/W, 648 MIX). No "first fill of the day" variant was needed, because nothing traded more than 2 per weekday.
  **Bonferroni two-sided 5% bar: |t| > 4.47.**
* **Ranking (prereg):** eligible if TRAIN n ≥ 40 and ≤ 3 trades/weekday (fallback n ≥ 20); score = TRAIN t-stat of net R; best per TF is frozen, then TEST is read.
  * **VIABLE** needs all of: TEST mean > 0 with CI lower bound > 0, still > 0 at 1.5× costs and at 5-min delay, ≥ 3/5 TEST quarters > 0, n ≥ 20.

## 2. Best per TF (selected on TRAIN, frozen), TEST after costs

R per trade. CI = 95%. Hold = average time in trade. Cost/risk = (spread + commission + 1 slippage leg) / risk, median. Gross = before costs.

| TF | Config (TRAIN-selected) | TRAIN n / net (t) | TEST n | /wd | WR | **TEST net [CI]** | PF | maxDD R | Losing streak | Hold | Cost/risk | Gross TRAIN / TEST | TEST 1.5× cost / 5-min delay | TEST qtrs > 0 | PRE 2020-22 n / net | Verdict |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|---|---:|---|---|
| M5 | ≥5★, prox, SL eng, TP 2R, 3h, D1 trend, all | 43 / −0.190 (t −0.87) | 22 | 0.07 | 23% | **−0.356** [−0.90, +0.19] | 0.56 | 9.8 | 5 | 16 min | 0.13 | +0.114 / −0.302 | −0.383 / −0.462 | 2/5 | 63 / −0.026 | FAIL |
| M15 | ≥4★, prox, SL +0.1 ATR, TP 3R, 3h, D1 trend, LonNY | 50 / −0.054 (t −0.22) | 18 | 0.06 | 28% | **−0.131** [−0.85, +0.58] | 0.82 | 5.3 | 5 | 77 min | 0.07 | +0.174 / −0.102 | −0.145 / −0.131 | 2/5 | 49 / +0.174 | FAIL |
| M30 | ≥3★, mid, SL +0.1 ATR, TP 3R, 1h, no trend, LonNY | 65 / +0.153 (t 0.73) | 30 | 0.09 | 20% | **−0.545** [−0.94, −0.15] | 0.32 | 18.3 | 10 | 22 min | 0.06 | +0.297 / −0.432 | −0.556 / −0.545 | 0/5 | 95 / −0.088 | FAIL |
| H1 | ≥3★, prox, SL eng, TP 2R, 1h, H4 trend, all | 42 / −0.001 (t −0.01) | 17 | 0.05 | 41% | **−0.275** [−0.61, +0.06] | 0.40 | 4.7 | 5 | 41 min | 0.03 | +0.119 / −0.262 | −0.279 / −0.275 | 2/5 | 48 / +0.008 | FAIL |
| H4 | no config with TRAIN n ≥ 20 (max 9) | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |
| D1 | no config with TRAIN n ≥ 20 (max 4) | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |
| W | no config with TRAIN n ≥ 20 (max 1) | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |
| MIX-H4 (H4 zone, London/NY touch, ≤3h) | max TRAIN n = 7 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |
| MIX-D1 | max TRAIN n = 3 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |
| *X-H4 (exploratory, any virgin OB)* | any, prox, SL eng, TP 3R, 2h, no filter | 51 / −0.050 (t −0.45) | 18 | 0.06 | 50% | **−0.194** [−0.46, +0.07] | 0.43 | 4.9 | 4 | 100 min | 0.02 | +0.002 / −0.190 | −0.197 / −0.194 | 1/5 | 75 / −0.150 | FAIL |
| *X-D1 (exploratory)* | any, prox, SL eng, TP 3R, 3 days, no filter (n ≥ 20 fallback) | 20 / −0.013 (t −0.06) | 9 | 0.03 | 44% | **−0.071** [−0.58, +0.44] | 0.81 | 2.9 | 3 | 47 h | 0.00 | +0.024 / −0.050 | −0.083 / −0.071 | 3/5 | 27 / +0.368 | FAIL |
| *X-W (exploratory)* | max TRAIN n = 3 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | NO SAMPLE |

TRAIN side of the winners (same order):

| TF | /wd | WR | PF | maxDD R | Losing streak | Hold | Cost/risk |
|---|---:|---:|---:|---:|---:|---:|---:|
| M5 | 0.07 | 30% | 0.76 | 11.7 | 6 | 22 min | 0.28 |
| M15 | 0.08 | 28% | 0.93 | 10.9 | 6 | 51 min | 0.15 |
| M30 | 0.10 | 37% | 1.24 | 7.2 | 6 | 25 min | 0.21 |
| H1 | 0.06 | 43% | 1.00 | 6.5 | 7 | 38 min | 0.10 |

Per quarter: `winners*.json` holds TRAIN, TEST and PRE quarters. The M30 winner is negative in all 5 TEST quarters. The others are positive in 1–3 of 5, on 1–9 trades per quarter.

Top-5 TRAIN configs per TF on TEST (`top5_per_group_test*.csv`): **all 20 (M5/M15/M30/H1) are negative on TEST**. In the exploratory X-D1 group, ranks 3–5 are +0.15R on TEST with n = 9, which is noise.

## 3. The whole grid (not only the winners)

| TF | Configs | Eligible (n ≥ 40) | Net > 0 TRAIN (all / eligible) | Net > 0 TEST (all / eligible) | Gross > 0 TRAIN / TEST | Median eligible net TRAIN / TEST |
|---|---:|---:|---|---|---|---|
| M5 | 648 | 540 | 0 / 0 | 86 / 80 | 156 / 317 | −0.49 / −0.11 |
| M15 | 648 | 432 | 2 / 0 | 104 / 39 | 70 / 139 | −0.35 / −0.18 |
| M30 | 648 | 270 | 61 / 18 | 253 / 162 | 263 / 285 | −0.20 / +0.04 |
| H1 | 648 | 126 | 213 / 0 | 214 / 23 | 337 / 245 | −0.17 / −0.14 |
| H4, D1, W, MIX | 3,888 | 0 | (n ≤ 9: noise) | | | |

* **Many M30 configs are positive on TEST but not elsewhere.** 162 eligible M30 configs are positive on TEST. Only 1 of them is also positive on TRAIN, and only 1 on PRE-SAMPLE (their median PRE net is −0.20). That pattern fits a 2025-26 regime effect, not a stable edge.
  * Gold traded $1,805–3,500 in TRAIN (median D1 ATR $31) and $3,268–5,597 in TEST (median D1 ATR $99). The fixed $ costs therefore shrink relative to the stop. Median cost/risk on M30 fell from 0.16 in TRAIN to 0.06 in TEST.
  * Picking those configs now would mean selecting on TEST.
* **Positive in all three periods:** only 4 configs, all H1 ≥4★ prox + D1 trend, TP 1–2R, 1–3h. Their samples are 22 / 12 / 26 trades and their TRAIN t is 0.08–0.47. That is pure noise level, found after the fact. Not a finding.

## 4. Random-entry baseline (same holds, XAU; `random_baseline.csv`)

Setup: 3 random minutes per weekday, random side, market entry. SL = median engine OB risk for that TF (≈0.6 ATR(TF)), TP 1R.

* **Gross ≈ 0 everywhere**: within ±0.12R, mostly within ±0.05R, on M5–D1 at 1–3h. So the simulator has no hidden bias.
* **Net = pure cost drag** (TRAIN / TEST, TP 1R, 1h):

| TF | Net TRAIN | Net TEST |
|---|---:|---:|
| M5 | −0.46 | −0.24 |
| M15 | −0.32 | −0.11 |
| M30 | −0.20 | −0.11 |
| H1 | −0.15 | −0.06 |
| H4 | −0.09 | −0.03 |
| D1 | −0.03 | −0.00 |
| W | −0.01 | −0.00 |

* Long holds, where swap adds up:

| Hold | Net TRAIN | Net TEST |
|---|---:|---:|
| H4, 24h | −0.10 | −0.03 |
| D1, 3d | −0.06 | −0.09 |
| W, 14d | −0.08 | −0.03 |

* **The OB setups do no better than random before costs.** Their gross edge (§TL;DR table) sits inside the same ±0.1R band as random entries.

## 5. Why HTF cannot be tested here (diagnostic, `diagnostics_htf.txt`)

* **Engine zones on XAU, 2019-2026:**

| TF | Zones (≥2 detection stars) |
|---|---:|
| H4 | 148 |
| D1 | 34 |
| W | 5 |

  With validity ≤ 4d on H4, only 40% are touched in time. On D1, only 57% are touched within 28 days.
  Gold's one-way trend (2023-2026) means bull zones are rarely revisited, and bear zones get run over.
* **The 5th star at touch also matters.** For a ≥5★ HTF trade, the first touch must land in the London/NY windows. Otherwise the zone is no longer virgin and is dropped.
* **MIX, pooled 2020-2026** (≥3★, SL eng, all 3 periods together):

| Variant | n | Net | Gross |
|---|---:|---:|---:|
| H4 zone, market entry at the London/NY touch, TP 2R, 1h | 26 | −0.16R [−0.45, +0.12] | −0.11 |
| D1 zone, same | 7 | −0.11R | −0.09 |

  Even pooled over 6.75 years, there are too few trades to say anything, and the point estimate is negative.
* **Weekly** (exploratory "any virgin OB"): 6 fills in 6.75 years. That is not testable.

## 6. Verdict per TF

| TF | Verdict |
|---|---|
| M5 | **FAIL**. Costs ≈ 0.4–0.5R of risk with engine stops; gross ≈ 0. |
| M15 | **FAIL** |
| M30 | **FAIL**. The TRAIN winner is the worst on TEST, at −0.55R. |
| H1 | **FAIL**. Matches the earlier multi-asset study (≈0 gross, ≈ −0.2R net). |
| H4 / D1 / W | **Not testable with the scanner's 5★ engine on XAU** (≤ 9 TRAIN trades). The loosened exploratory version fails on TEST (H4 −0.19R, D1 −0.07R). |
| MIX (HTF zone + London/NY touch, ≤3h) | **Not testable** (≤ 7 TRAIN trades). Pooled 2020-26, 26 trades at −0.16R. |

**No rules to give: nothing is viable.** Do not trade OB alerts on XAU from this engine, on any TF, with real money.

## 7. Caveats

* The costs are assumptions for a good raw-spread account. Swap is a rough flat approximation, and only matters for holds of 1+ days.
  At half or zero cost, the gross numbers above (≈0) still show no edge.
* HistData/Dukascopy BID is used as mid. Your broker's gold feed and its spikes may differ.
* HTF conclusions are limited by sample size, not by evidence of a loss. "Kasper-style" HTF OBs drawn by hand are probably looser than this engine's definition, and that is not what was tested.
  A proper HTF test would need a different zone definition, multi-asset pooling for sample size, and a new pre-registration.
* The exploratory family X and the §3/§5 diagnostics were added after the main results. They are logged as a deviation in the prereg and cannot count as evidence.

## Reproduce
```bash
.venv/bin/python scripts/strategy_research/ob_xau_multitf.py detect        # ~12 min on 7 cores (needs XAUUSD_M1_2019_2022.parquet, see prereg)
.venv/bin/python scripts/strategy_research/ob_xau_multitf.py grid          # ~2.5 min
.venv/bin/python scripts/strategy_research/ob_xau_multitf.py select
.venv/bin/python scripts/strategy_research/ob_xau_multitf.py baseline
.venv/bin/python scripts/strategy_research/ob_xau_multitf.py detect_x && .venv/bin/python scripts/strategy_research/ob_xau_multitf.py grid_x && .venv/bin/python scripts/strategy_research/ob_xau_multitf.py select_x
```
The 2019-2022 file was built with `fetch_histdata.dl/parse` for `xauusd` 2019–2022 and saved as `data/cache/strategy_research/m1/XAUUSD_M1_2019_2022.parquet` (gitignored).
