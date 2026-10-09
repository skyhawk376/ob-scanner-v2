# WR ≥ 70 % OB strategy — results (2026-10-09)

Protocol: `PREREG_WR70.md` (commit 07da914) → simulator check (BE off == common.simulate, max |ΔR| = 0) + TRAIN grid of 75 configs
and selection committed (57e837e) → TEST read once (`evaluate_test.py`). Sample: 21.9k touched ≥4★ Filtre B zones, 14 symbols,
M5–H4, 2023-01 → 2026-09; TRAIN t₀ < 2025-07-01 ≤ TEST. Realistic M1 sim: fill required, 3-min manual delay, SL-first on
ambiguous bars, every trade closed by TP/SL/time stop, per-asset costs. Win = net R > 0.

## TRAIN (75 configs)
**No config reached the pre-registered bar (TRAIN WR ≥ 72 % with ≥ 300 trades). Best TRAIN WR = 69.0 %** (E1 mid limit, TP 0.3R,
3h, H1+H4 only) — selected per the fallback rule and flagged. All 75 configs had negative TRAIN net R (best −0.12R).
Break-even (move SL to entry at +0.5·TP) destroys WR (21–28 %): with TP ≤ 1R most trades that run first touch BE before TP.
Lower-TF filters matter: with M5 or crypto included, costs (often 0.2–0.5 R per trade) turn TP-0.3R "wins" into net losses (WR 42–56 %).

## TEST (2025-07 → 2026-09), read once
| config (TRAIN rank) | n | /day | WR net | WR gross | gross R [95 % CI] | net R [95 % CI] | PF | maxDD R | hold min | cost R | random net mean / p95 (WR) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **#1 selected: E1 mid limit, TP 0.3R, 3h, H1+H4** | 421 | 1.3 | **66.7 %** | 71.5 % | −0.032 [−0.087, +0.023] | **−0.184 [−0.244, −0.125]** | 0.47 | 80 | 15 | 0.09 | −0.260 / −0.176 (59 %) |
| #2 E1 mid limit, TP 0.3R, 1h, H1+H4 | 421 | 1.3 | 63.9 % | 68.9 % | −0.040 [−0.094, +0.014] | −0.193 [−0.251, −0.134] | 0.44 | 83 | 13 | 0.09 | −0.218 / −0.161 (54 %) |
| #3 E3 sweep & reclaim, TP 0.3R, 3h, cost ≤ 0.10R | 1982 | 6.1 | 67.2 % | 70.0 % | −0.054 [−0.080, −0.029] | −0.164 [−0.191, −0.137] | 0.48 | 326 | 26 | 0.05 | −0.227 / −0.146 (66 %) |
| #4 E2 T3 retest limit, TP 0.3R, 3h, cost ≤ 0.10R | 1685 | 5.2 | 64.6 % | 67.2 % | −0.026 [−0.052, +0.001] | −0.115 [−0.143, −0.087] | 0.62 | 194 | 40 | 0.05 | −0.195 / −0.123 (67 %) |
| #5 E1 mid limit, TP 0.3R, 3h, cost ≤ 0.10R | 1523 | 4.7 | 62.9 % | 68.5 % | −0.043 [−0.072, −0.013] | −0.192 [−0.224, −0.159] | 0.48 | 293 | 9 | 0.05 | −0.289 / −0.204 (61 %) |

TRAIN → TEST WR: #1 69.0 → 66.7 %, #2 65.8 → 63.9, #3 65.7 → 67.2, #4 63.8 → 64.6, #5 63.6 → 62.9 (stable, but all < 70 %).
Random baseline = same zones, market entry at a random minute in [touch, touch + W], same SL price, same TP multiple/hold/costs (200 draws).
#4 and #5 beat random p95 (some timing/placement value) but stay clearly negative.

Selected config, why it loses: exits 67.9 % TP / 31.8 % SL / 0.2 % time. Avg net win +0.24 R, avg net loss −1.04 R →
break-even WR after costs ≈ 81 %; observed 66.7 %. Pre-cost the market is roughly a coin flip at these distances
(gross ≈ −0.03 R, CI includes 0); costs (0.09 R/trade) make it clearly negative.

## Breakdown — selected (TEST net R)
| TF | n | /day | WR | net R [CI] |
|---|---|---|---|---|
| H1 | 382 | 1.2 | 65.7 % | −0.201 [−0.265, −0.138] |
| H4 | 39 | 0.1 | 76.9 % | −0.019 [−0.188, +0.149] |

| group | n | WR | net R [CI] |
|---|---|---|---|
| CRYPTO | 116 | 70.7 % | −0.147 [−0.257, −0.038] |
| FOREX | 258 | 63.2 % | −0.239 [−0.317, −0.162] |
| METALS | 47 | 76.6 % | +0.026 [−0.137, +0.190] (n small, CI spans 0) |

## Verdict
* No OB configuration in the 75 pre-registered ones reaches 70 % WR on TEST; best 67.2 % (#3), selected 66.7 %.
* None is profitable after costs: every candidate's TEST net R CI is entirely below 0 (−0.12 to −0.19 R per trade).
* A ≥ 70 % WR at TP 0.3R would need ≥ ~81 % to break even after costs. High WR here = many small wins, a few full-R losses.
* H4 and metals subsets show WR > 75 % but n = 39 / 47 and net CIs span 0 — not evidence (post-hoc, not pre-registered).
