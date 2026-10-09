# Reversal-candle entry — results (2026-10-09)

Protocol: `PREREG_REVERSAL.md` (commits 489f3ac, f50d0ad T5, b88e527 T6) → TRAIN grid + selection committed (c75bbfe) → TEST read once
(`evaluate_test.py`). Sample: 21.9k touched ≥4★ Filtre B zones, 14 symbols, M5–H4, 2023-01 → 2026-09; TRAIN < 2025-07-01 ≤ TEST.
Realistic M1 sim, per-asset costs, 3-min manual latency on every trigger, SL-first on ambiguous bars.
Implementation note (applied before TEST, per prereg "skip if fill ≤ SL"): orders whose fill is already through the SL are dropped
(209 T0 trades on TRAIN — a simulator artefact made them look like wins). T0 TEST net therefore −0.633 vs −0.629 in the previous report.

TRAIN selection (best TRAIN net with ≥300 trades): T1 same/zone/3h, T2 same/zone/3h, T3 retest/zone/3h, T4 same/zone/3h, T5a/3h;
T6 = T4 same/zone/3h else T5a. 3h hold beat 1h and zone-SL beat candle-SL in every family (candle SL → tiny risk → costs explode).

## TEST (2025-07 → 2026-09)
| config | n | /day | WR | gross R | net R [95 % CI] | PF | maxDD R | hold min | random p95 | Δ vs T0 [CI] | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T0 prod limit, 1h | 6835 | 21.0 | 28.5 % | −0.024 | −0.645 [−0.683, −0.606] | 0.39 | 4407 | 15 | – | – | – |
| T0 prod limit, 3h | 6835 | 21.0 | 27.9 % | −0.017 | −0.633 [−0.672, −0.593] | 0.42 | 4325 | 22 | – | – | – |
| T1 engulfing | 2170 | 6.7 | 30.0 % | −0.078 | −0.406 [−0.463, −0.349] | 0.49 | 885 | 77 | −0.364 | +0.23 [0.16, 0.30] | no |
| T2 pin bar | 2217 | 6.8 | 28.1 % | −0.078 | −0.610 [−0.705, −0.515] | 0.39 | 1354 | 64 | −0.467 | +0.02 [−0.08, 0.13] | no |
| T3 LTF CHoCH, limit on retest | 2854 | 8.8 | 31.8 % | −0.067 | **−0.274** [−0.318, −0.231] | 0.60 | 785 | 81 | −0.305 ✔ | +0.36 [0.30, 0.42] | no (net < 0) |
| T4 close back out of zone | 5214 | 16.0 | 31.9 % | −0.022 | −0.388 [−0.435, −0.341] | 0.52 | 2026 | 77 | −0.375 | +0.25 [0.18, 0.31] | no |
| T5a sweep & reclaim (standalone) | 4235 | 13.0 | 36.9 % | +0.035 | −0.323 [−0.366, −0.280] | 0.61 | 1370 | 61 | −0.312 | +0.31 [0.25, 0.37] | no |
| **T6 = T4 else T5a (user rule)** | 6610 | 20.3 | 34.0 % | 0.000 | −0.355 [−0.395, −0.315] | 0.55 | 2351 | 74 | −0.333 | +0.28 [0.22, 0.33] | no |

Random baseline = same zones, market entry at a random minute in [touch, touch+3h], same SL price, TP 2R, same hold (200 draws).
Gross R 95 % CI: T0 [−0.05, +0.02], T3 [−0.11, −0.02], T5a [−0.005, +0.075], T6 [−0.03, +0.03].
**Why net improves but gross doesn't:** triggered entries sit further from the distal edge → median risk 1.2–1.7 ATR vs 0.62 ATR for T0
→ round-trip cost per R halves (median commission/risk 0.08–0.11 vs 0.21). Random entries in the same zones with the same SL get most
of that improvement (random mean −0.40 to −0.67). No trigger adds timing edge before costs.

Secondary (cost filter commission/risk ≤ 0.10): T0 −0.162 [−0.23, −0.10]; T3 −0.166; T4 −0.156; T5a −0.128 [−0.18, −0.07]; T6 −0.141 [−0.18, −0.10]. None > 0.

## Breakdowns (TEST net R)
| TF | T0 3h | T3 | T6 |
|---|---|---|---|
| M5 | −0.82 (13.2/d) | −0.32 (6.3/d) | −0.46 (12.8/d) |
| M15 | −0.39 (4.3/d) | −0.17 (1.8/d) | −0.17 (4.2/d) |
| M30 | −0.28 (2.1/d) | −0.10 (0.4/d) | −0.21 (2.1/d) |
| H1 | −0.18 (1.2/d) | −0.24 (0.2/d) | −0.16 (1.1/d) |
| H4 | +0.15 (n=41) | n=1 | −0.14 (n=27) |

| group | T0 3h | T3 | T6 |
|---|---|---|---|
| CRYPTO | −0.94 | −0.38 | −0.55 |
| FOREX | −0.54 | −0.26 | −0.29 |
| METALS | −0.29 | −0.12 [−0.24, +0.01] | −0.16 |

T6 sources: 4526 reversal trades (−0.37R) + 2084 sweep&reclaim late entries (−0.33R).

## "Fake signals" filtered (zones vs T0 3h on TEST)
| | T0 losers skipped | T0 winners kept | trades/day vs T0 |
|---|---|---|---|
| T1 engulfing | 76 % | 48 % | −68 % |
| T2 pin bar | 72 % | 41 % | −68 % |
| T3 CHoCH retest | 72 % | 72 % | −58 % |
| T4 close-back | 38 % | 99 % | −24 % |
| T5a | 27 % | 35 % | −38 % |
| T6 | 10 % | 99 % | −3 % |
(T3 removes most zones that fail, but its later/higher entry leaves less room, so gross R does not improve.)

Visual: `/workspace/ob_shape/reversal_examples.png` (T6 examples: 2 wins, 2 losses).
