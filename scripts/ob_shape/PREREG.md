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
