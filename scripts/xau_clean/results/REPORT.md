# XAUUSD clean-OB study (M5/M15/M30/H1) — results (2026-10-09)

Protocol: PREREG_XAU_M5_CLEAN.md (dc5aae9, scope widened to 4 TFs before outcomes) → TRAIN grid 4 TF × 6 filters × 24 configs + per-cell
selection committed → TEST read once (`run.py test`). wr70 simulator (realistic M1, 3-min delay, SL-first, XAU costs), TRAIN < 2025-07-01 ≤ TEST.
No cell reached TRAIN WR ≥ 72 % with ≥ 20 trades → every pick is the fallback (highest TRAIN WR, flagged). 13/24 cells had < 20 TRAIN
trades (Q4/Q5 everywhere, Q3 on M15+, Q2 on M30/H1, Q1 on H1) → "insufficient", no TEST pick.

## TEST (selected config per TF × filter)
| TF | filter | config | zones TEST | trades | /day | WR net | gross R | net R [95 % CI] | PF | maxDD R | random mean / p95 | TRAIN n / WR / net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M5 | base | E3 sweep&reclaim tp0.3 3h | 301 | 202 | 0.62 | 62.4 % | −0.103 | −0.187 [−0.27, −0.10] | 0.46 | 38.7 | −0.24 / −0.01 | 385 / 58 % / −0.31 |
| M5 | Q1 textbook | E2 retest tp0.3 3h | 90 | 39 | 0.12 | **71.8 %** | +0.036 | +0.012 [−0.17, +0.20] | 1.05 | 3.9 | −0.04 / +0.10 | 82 / 60 % / −0.20 |
| M5 | Q2 strict | E3 tp0.5 1h | 32 | 14 | 0.04 | **71.4 %** | +0.177 | +0.025 [−0.34, +0.40] | 1.08 | 1.8 | −0.33 / +0.16 | 24 / 58 % / −0.44 |
| M5 | Q3 impulse | E3 tp0.5 3h | 17 | 12 | 0.04 | 58.3 % | −0.037 | −0.084 [−0.47, +0.30] | 0.75 | 3.1 | −0.11 / +0.30 | 21 / 52 % / −0.35 |
| M15 | base | E2 tp0.3 3h | 98 | 40 | 0.12 | **72.5 %** | +0.010 | −0.001 [−0.18, +0.18] | 0.99 | 2.7 | +0.02 / +0.14 | 72 / 61 % / −0.13 |
| M15 | Q1 | E2 tp0.3 3h | 37 | 18 | 0.06 | 66.7 % | −0.069 | −0.079 [−0.35, +0.19] | 0.72 | 2.6 | +0.01 / +0.18 | 25 / 68 % / +0.00 |
| M15 | Q2 | E1 mid limit tp0.3 1h | 6 | 6 | 0.02 | 50.0 % | +0.026 | −0.236 [−0.73, +0.26] | 0.38 | 2.0 | −0.46 / +0.18 | 23 / 57 % / −0.31 |
| M30 | base | E1 tp0.3 1h | 35 | 28 | 0.09 | 67.9 % | −0.037 | −0.063 [−0.29, +0.16] | 0.78 | 3.2 | −0.04 / +0.11 | 99 / 65 % / −0.16 |
| M30 | Q1 | E1 tp0.3 1h | 11 | 10 | 0.03 | **70.0 %** | +0.034 | +0.007 [−0.35, +0.37] | 1.03 | 1.2 | −0.04 / +0.21 | 33 / 64 % / −0.17 |
| H1 | base | E1 mid limit tp0.3 3h | 33 | 29 | 0.09 | **86.2 %** | +0.174 | **+0.162 [+0.007, +0.318]** | 2.38 | 1.0 | −0.03 / +0.10 | 47 / 70 % / −0.07 |
Insufficient (< 20 TRAIN trades): M5 Q4/Q5, M15 Q3/Q4/Q5, M30 Q2–Q5, H1 Q1–Q5.

## Answers
* ≥ 70 % TEST WR: M5 Q1 (71.8 %, n=39), M5 Q2 (71.4 %, n=14), M15 base (72.5 %, n=40), M30 Q1 (70.0 %, n=10), H1 base (86.2 %, n=29).
* Best per TF (TEST net, ≥10 trades; TEST-chosen): M5 Q2 +0.025 R (n=14), M15 base −0.001 R, M30 Q1 +0.007 R (n=10), H1 base +0.162 R.
* Best overall: **H1, all XAU zones (no quality filter), prod mid limit, TP 0.3 R, 3 h time stop** — 29 trades in 15 months
  (≈ 0.09/day, ~2 per month), WR 86 %, net +0.16 R [+0.007, +0.318], beats random p95. It is the only cell with net CI > 0 → nominally
  "profitable after fees", BUT: n = 29, the lower bound is barely above 0, its TRAIN net was −0.07 R (WR 70 %), and it is one of
  11 TEST cells (plus 576 TRAIN configs) → this is very likely luck / regime (gold's 2025-26 trend), not a proven edge.
  The quality filters did not help it (H1 Q1–Q5 had too few zones).
* Clean-zone filters: on M5, Q1/Q2 lift WR above 70 % on TEST with net ≈ 0 (CI spans 0, n 14–39); on TRAIN the same configs were
  clearly negative (−0.20 / −0.44 R). Q3/Q4/Q5 leave too few zones to say anything. No evidence that "clean" zones are profitable.
* Verdict: nothing is a reliable profitable strategy after fees. The XAU H1 TP 0.3R rule is the only candidate worth paper-trading /
  forward-testing (small size), not trading for real on this evidence.

## Files
`test_table.csv`, `train_grid.csv`, `selection.json`; retained TEST zones of each TF's best filter:
`test_zones_M5_Q2.csv`, `test_zones_M15_base.csv`, `test_zones_M30_Q1.csv`, `test_zones_H1_base.csv`
(date Paris, direction, zone top/bot, size $, entry, SL, tb_fails, outcome tp/sl/time/no trade, net R).
