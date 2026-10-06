# Pre-registration #3: OB 5★ on XAUUSD only, multi-timeframe (M5 M15 M30 H1 H4 D1 W)

Written 2026-10-06 ~14:57 CEST (Europe/Paris), **before any backtest result of this study**. Only zone detection was running at
that point; detection is not a performance result. Script: `scripts/strategy_research/ob_xau_multitf.py`.
Outputs: `data/backtest/strategy_research/ob_xau/`. Report: `OB_XAU_MULTITF.md`. Research only: no deploy, no push.

## Data and split
* XAUUSD M1, HistData (= Dukascopy BID, treated as mid). The framework file covers 2023-01-02 → 2026-09-30.
  **2019-2022 was added** from the same source (HistData yearly files), for two uses only:
  (a) detection warm-up, so D1 and W have real context in 2023;
  (b) a supplementary **PRE-SAMPLE** hold-out (fills 2020-01-01 → 2022-12-31), read only for the frozen winners.
  It is never used to select anything.
* **TRAIN** = fills 2023-01-02 → 2025-06-30. **TEST** = fills from 2025-07-01 → 2026-09-30. All selection uses TRAIN only.

## Execution (identical to the framework, `common.py`)
* Fills use the `common._sim` numba core unchanged:
  * Limit orders fill only on trade-through by half the spread.
  * SL wins when SL and TP are hit in the same minute.
  * On the fill bar, TP counts only on a close beyond it.
  * Stop and market legs pay the half-spread plus slippage. Gaps fill at the worse open.
* Costs, XAU 1×: spread $0.25, commission $0.07 round trip, slippage $0.10 per stop or market leg.
* **Overnight swap** (added because holds go up to 4 weeks), approximated as below. Swap is in net R, scaled by the cost multiplier, and excluded from gross:
  * Long pays 0.020% of price per 17:00 New York rollover. Short pays 0.010%. Both sides are charged (conservative).
  * The Wednesday rollover counts ×3.
* Alert delay: an order is live **3 min** after the signal bar closes. Stress test: 5 min.
* R = |entry level − SL|. Gross = zero cost (no spread, commission, slippage or swap).

## Bars and detection
* Bars are built from M1 and labelled by open time:
  * M5 / M15 / M30 / H1 / H4 are UTC-aligned.
  * D1 uses the 17:00 New York roll.
  * W = Monday-week of D1 bars (opens Sunday 17:00 NY).
* Repo engine `detect_zones` is used **unchanged**: virgin OB + FVG (★1) required, entry_mode "mid", `sl_buffer_atr` 0.05.
* Params per TF:

| TF | pivot_n | lookback (bars) | Source |
|---|---:|---:|---|
| M5 | 3 | 300 (≈25 h) | adapted, same as prereg #2 |
| M15 | 3 | 300 | adapted, same as prereg #2 |
| M30 | 3 | 300 | adapted, same as prereg #2 |
| H1 | 3 | 500 | `params_for_tf` |
| H4 | 3 | 500 | `params_for_tf` |
| D1 | 2 | 400 | `params_for_tf("D")` |
| W | 2 | 260 | `params_for_tf("W")`, limited by available history: about 200 weekly bars before 2023, 60-bar warm-up |

* Causal walk-forward. At every bar j the engine gets `bars[j-lookback-2 : j+1]` and drops bar j as forming, so a zone is known at the
  open of bar j (= close of bar j−1).
* For each zone (direction, OB time), the **first time** its score reaches each level is recorded.
* **Stars on M5–H1:** engine score, where ★5 = session of the OB candle (engine).
* **Stars on H4/D1/W:** the engine leaves ★5 pending until touch. Effective stars = detection score + 1 if the **first touch** falls in an engine window: London 08:00–11:30 or NY 14:30–17:30 Paris. A touch is the first M1 bar after the order goes live that reaches the proximal edge.
  * For min stars L, the order is live from the first time the detection score reached L−1.
  * The trade is kept only if (touch in an engine window) OR (detection score ≥ L was reached before the touch).
  * Otherwise the zone is discarded, because once touched it is no longer virgin.
* "Virgin" is always on, since the engine requires it. It is not a grid dimension.

## Main grid per TF (family Z)
| Dimension | Values |
|---|---|
| min stars | ≥3, ≥4, ≥5 |
| entry (limit) | **mid** = engine entry (zone mid if height > 1 ATR(TF), else OB open); **prox** = proximal edge |
| SL | **eng** = distal ∓ 0.05 ATR(TF) (engine); **buf** = distal ∓ 0.10 ATR(TF) |
| TP | 1R, 2R, 3R |
| hold (time stop after fill) | all TFs: 1 h, 2 h, 3 h; plus H4: 24 h, 48 h; D1: 3 d, 5 d; W: 14 d, 28 d (calendar time) |
| trend at alert (last closed bar) | none / H4 close vs EMA50 aligned / D1 close vs EMA50 aligned |
| session | all / **LonNY** (see below) |

* **LonNY** = fill minute in 08:00–12:00 or 14:30–18:00 Paris. Operationally the order is only live in those windows, and a trade-through outside them consumes the zone.
* **Limit validity after the alert:**

| TF | Validity |
|---|---|
| M5 | 2 h |
| M15 | 6 h |
| M30 | 12 h |
| H1 | 24 h |
| H4 | 4 days |
| D1 | 28 days |
| W | 84 days |

* Configs: 648 per TF for M5–H1 and 1080 per TF for H4/D1/W, so **5,832** in total.

## Mixed idea (family MIX): HTF zone, entry only when price reaches it during London/NY, hold ≤ 3 h
* Zone source: H4 or D1 (treated as two separate "TFs"), engine as above.
* The first touch of the zone must happen inside the engine windows (London 08:00–11:30 / NY 14:30–17:30 Paris) and within the validity above. Otherwise the zone is discarded.
* Alert at the close of the M5 bar containing the touch. The order is live 3 min later.
* Effective stars = detection score at touch + 1 (★5 met by construction). Min stars: ≥3, ≥4, ≥5.
* Entry: **market**, or **limit at the engine mid**, valid 60 min.
* SL eng / buf. TP 1/2/3R. Hold 1/2/3 h. Trend (evaluated at touch): none / H4 EMA50 / D1 EMA50.
* Configs: 2 × 3 × 2 × 2 × 3 × 3 × 3 = **648**.

## First-fill-of-the-day variants
Every config with more than 2.0 TRAIN trades per weekday also enters as a "first fill of the day (Paris)" variant. These variants are counted in K.

**K (base) = 6,480**, plus fod variants. Bonferroni two-sided 5% bar: |t| > 4.47 at K = 6,480. The exact value is recomputed with the final K.

## Ranking rule (frozen)
1. Groups: M5, M15, M30, H1, H4, D1, W, MIX-H4, MIX-D1.
2. Eligible on TRAIN: n ≥ 40 trades and ≤ 3.0 trades/weekday. If a group has no eligible config, fall back to n ≥ 20 and flag the group "insufficient sample".
3. Score = TRAIN t-statistic of mean net R (1× costs). **Best per group** = highest score. It is frozen, and only then is TEST read.
4. **Verdict per group (on TEST, frozen config):**
   * **VIABLE** only if all of these hold:
     * TEST mean net R > 0, with 95% CI lower bound > 0;
     * TEST mean still > 0 at 1.5× costs and with a 5-min delay;
     * ≥ 3 of 5 TEST quarters > 0;
     * TEST n ≥ 20.
   * **PROMISING:** TEST mean > 0 but one of the conditions above fails.
   * **FAIL:** TEST mean ≤ 0.
   * Whether the TRAIN t of the winner clears the Bonferroni bar is reported separately.
5. Overall pick (if any) = the VIABLE group with the highest TRAIN score.
6. **Reported for every winner:**
   * TRAIN and TEST after costs: n, trades/weekday, WR, avg R with 95% CI, PF, maxDD (R), longest losing streak, avg hold, cost/risk.
   * Cost/risk = (spread + commission + one slippage leg) / risk.
   * Gross (before costs) edge.
   * Per quarter.
   * 1.5× costs and 5-min delay stress.
   * PRE-SAMPLE 2020–2022 (supplementary).
   * Top-5 TRAIN configs per group on TEST.
   * Share of configs with net > 0 on TRAIN and on TEST.
7. **Random-entry baseline (not ranked):** XAU, 3 random minutes per weekday (all hours, and LonNY), random side, market entry. SL = (median engine risk/ATR(TF) of that TF's ≥3★ zones) × ATR(TF), as-of. TP 1/2/3R, same holds as the TF. Gross and net, TRAIN and TEST.

No deviations are allowed without being logged below with a timestamp.

## Deviations / clarifications (logged after the runs)
(none yet)
