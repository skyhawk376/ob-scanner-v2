# XAUUSD clean-OB study (M5, M15, M30, H1) — pre-registration

Written 2026-10-09 ~20:10 Paris, BEFORE any outcome of this study (TRAIN or TEST). Only zone counts were looked at.
Updated ~20:15 (still before outcomes): scope widened by the user from M5 only to M5, M15, M30, H1; results reported per TF.
Disclosure: earlier pooled studies (ob_shape, wr70) included XAU zones (metals subsets were shown on TEST, e.g. TP 0.3R H1+H4
metals n=47). Textbook filtering (tb_fails ≤ 1) was worse than random on the pooled TEST in ob_shape. Nothing on these exact
XAU-by-TF quality subsets has been computed.

## Sample / simulator
Zones `scripts/ob_shape/results/hist_zones.parquet`, sym = XAUUSD, tf ∈ {M5, M15, M30, H1}. Entry events
`scripts/reversal_entry/results/events.parquet`; simulator/costs `scripts/wr70/sim.py` (== strategy_research/common.py; XAU
spread 0.25 $, commission 0.07 $ RT, slip 0.10 $ per stop/market leg), fill required, 3-min manual delay, SL-first on ambiguous bars,
every trade closed by TP/SL/time stop. TRAIN t₀ < 2025-07-01 ≤ TEST. Win = net R > 0.

## Quality filters (features from scripts/ob_shape/features.py, textbook T1–T8 of ob_shape/PREREG.md)
* base: all XAU zones of the TF
* Q1 textbook: tb_fails ≤ 1
* Q2 strict textbook: tb_fails = 0
* Q3 strong impulse: disp_maxbody_atr ≥ 1.5 AND fvg_atr ≥ 0.5 AND ob_body_ratio ≥ 0.5
* Q4 clean structure: T6 not born in chop (chop10 ≤ 5) AND clear BOS (T3 BOS ≤ 10 bars AND T4 BOS margin ≥ 0.10 ATR) AND sweep_leg = 1
* Q5 = Q3 AND Q4
Zone counts TRAIN/TEST: M5 base 563/301, Q1 171/90, Q2 42/32, Q3 35/17, Q4 20/12, Q5 3/2; M15 198/98, 70/37, 23/6, 12/5, 7/1, 1/0;
M30 110/35, 36/11, 12/2, 8/2, 3/0, 1/0; H1 54/33, 21/9, 4/0, 4/1, 1/0, 0/0. **Most cells are too small to conclude anything.**

## Grid per (TF, filter): 24 configs
entry {E1 mid limit (prod entry, +3 min), E2 T3 LTF swing-break retest limit, E3 sweep & reclaim} × TP {0.3, 0.5, 1.0, 2.0} R
× time stop {1h, 3h}. (4 TF × 6 filters × 24 = 576 TRAIN evaluations — heavy multiple testing; TEST is read only for the
selected config per cell.)

## Selection (TRAIN, per TF × filter)
Highest TRAIN net avg R among configs with TRAIN WR ≥ 72 % and ≥ 20 TRAIN trades. If none: highest TRAIN WR among configs
with ≥ 20 trades (flagged). If no config has 20 trades: cell reported as "insufficient" (no TEST pick).

## TEST (read once)
Per selected cell: zones retained, trades, trades/weekday, WR net, gross R, net R [95 % CI], PF, max DD, random baseline
(same filled zones, market at random minute in [t₀, t₀ + hold], same SL price/TP/hold/costs, 200 draws; mean, p95).
Flags: WR ≥ 70 %; profitable after fees = net CI lower bound > 0. Best per TF and overall = highest TEST net R among cells with
≥ 10 TEST trades (descriptive, TEST-chosen → labelled as such).
CSV per TF: retained TEST zones of that TF's best filter (date Paris, direction, zone size $, entry/SL, outcome of the selected
config: tp/sl/time/no trade, net R).
