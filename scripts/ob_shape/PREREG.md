# OB shape study — pre-registration (written before looking at any outcome)

Written 2026-10-08 ~10:40 Paris, before any success/failure comparison was run.

## Samples
* **Prod**: every zone touched in prod (`/zones?statuses=reaction,echec,touchee`, all 7 TFs), snapshot 2026-10-08 ~10:00 Paris.
* **History**: scanner-parity engine (`tradingview/pine_reference.py`) on research M1 data (14 Filtre B symbols:
  XAU, XAG, 9 FX, BTC/ETH/SOL), 2023-01-02 → 2026-09-30, TFs M5/M15/M30/H1/H4. Listed = ≥4★ at alert time + ★1, touched.
* **Split**: TRAIN = touch < 2025-07-01, TEST = touch ≥ 2025-07-01 (same split as scripts/strategy_research).
  Feature exploration and rule selection use TRAIN (+ prod only as a qualitative check). TEST is read once.

## Outcomes
* `life`  : scanner status (reaction/échec) — what Telegram reports.
* `hold`  : did the OB hold — mid/open limit fills, then +2R before SL (TF bars, SL first) → tp / sl.
* `r_net` : realistic live trade (prod trade_sim rules) on M1 with per-asset costs; `r_gross` = zero cost.

## "Textbook OB" criteria (fixed now, not tuned)
| id | criterion |
|---|---|
| T1 | displacement: max body of OB+1..OB+2 ≥ 1.0 ATR |
| T2 | FVG (OB vs OB+2) ≥ 0.25 ATR |
| T3 | BOS within 10 bars of the OB |
| T4 | BOS close beyond the broken pivot by ≥ 0.10 ATR |
| T5 | OB is the origin of the move: leg extreme ≤ 0.10 ATR beyond the zone's distal edge |
| T6 | not born in chop: ≤ 5 of the 10 bars before the OB overlap the zone |
| T7 | OB candle body ≥ 25 % of its range (not a wick-only zone) |
| T8 | 0.2 ≤ zone height ≤ 2.5 ATR |

"Not textbook" = fails ≥ 2 of T1–T8 (also reported per criterion).

## Filter test protocol
1. On TRAIN only: rank features by univariate separation (hold tp-rate and r_net), bucket tables.
2. Write 2–3 candidate rules (simple thresholds, interpretable) into this file + commit **before** computing TEST.
3. TEST: trades kept, WR, avg R gross/net, 95 % CI, vs the unfiltered baseline and vs a random subset of the same size (1000 draws).

## Addendum — candidate rules, fixed after TRAIN exploration, BEFORE reading TEST (2026-10-08 ~11:20 Paris)

TRAIN findings that motivated them (`explore_train.py`, `explore_confirm_entry.py`):
* No OB-shape feature separates hold-tp from hold-sl (all |AUC − 0.5| ≤ 0.02 pooled; ≤ 0.04 on H1).
  Only touch-bar features separate (touch candle body/close-through), but they are known only after the fill
  (the SL is usually hit inside that candle). A "wait for a rejection close, then arm the limit" entry did not
  help on TRAIN (pooled gross −0.009 vs +0.004).
* Textbook score (T1–T8): 0 fails −0.054R gross vs 4 fails +0.043R — no benefit on TRAIN.
* Approach speed (ATR/bar from the post-BOS extreme to the touch): slow quintile +0.07R gross, fast −0.02/−0.06.
* Cost in R is by far the largest driver of NET (cost_r ≤ 0.05: −0.13R net; > 0.4: −1.5R net).

Rules (applied to the realistic live sim, all TFs pooled, also shown per TF):
* **R1 textbook**: tb_fails ≤ 1 (the user's hypothesis "fake OBs lose").
* **R2 slow approach**: approach_speed ≤ 0.40 ATR/bar (≈ TRAIN 40th pct; known before the touch).
* **R3 cost-aware**: cost_r ≤ 0.10 (planned risk ≥ 10× round-trip cost; drops micro zones).
* **R2+R3** combined.
Pass bar: TEST net > 0 with 95 % CI above 0, and filtered mean above the 95th pct of random same-size subsets.
