# WR ≥ 70 % — crypto (BTC/ETH/SOL), M5 zones, alerts 15:00–17:00 Paris — results (2026-10-09)

Protocol: `PREREG_WR70_CRYPTO_1517.md` (3df6aa0) → TRAIN grid + selection (1138f1c) → TEST read once (`crypto1517.py test`).
Same simulator/costs/split as the main WR70 study (fill required, 3-min delay, SL-first, per-asset crypto costs:
0.01 % spread, 0.05 % round-trip commission, 0.02 % slippage per stop/market leg). Alert time = first M1 touch, Paris local, DST-aware.
120 configs = 3 entries × TP {0.3, 0.5, 0.75, 1.0} R × time stop {1h, 3h} × filter {all, cost ≤ 0.10 R, BTC, ETH, SOL}.
Full TEST table: `test_table_full.md` / `test_grid.csv`.

## Sample is tiny
TEST trades per config: 0–183 (≤ 0.56/day). E1 (mid limit) with cost ≤ 0.10 R = **0 trades** in both periods: on crypto M5 the
zone risk is so small that commission alone is > 0.10 R on every trade (avg cost 0.15–0.33 R/trade for the "all" filter).
E1 1h and 3h are identical (all trades end by TP/SL within the hour).

## TRAIN
No config reached TRAIN WR ≥ 72 % with ≥ 100 trades → fallback = highest TRAIN WR with ≥ 100 trades:
**E2 (T3 retest limit), TP 0.3 R, 3h, all** (TRAIN n=144, WR 59.0 %, net −0.285 R). All configs with ≥ 100 TRAIN trades were negative.

## TEST
| config | n | /day | WR net | gross R | net R [95 % CI] | PF | maxDD R | random mean / p95 |
|---|---|---|---|---|---|---|---|---|
| **selected E2 tp0.3 3h all** | 94 | 0.29 | 50.0 % | −0.194 | −0.450 [−0.61, −0.29] | 0.22 | 43 | −0.71 / −0.23 |
| only ≥70 % WR: E3 sweep&reclaim tp0.3 3h cost≤0.10 | 39 | 0.12 | 71.8 % | −0.029 | −0.120 [−0.30, +0.06] | 0.57 | 6.2 | −0.28 / +0.02 |
| best net overall: E3 tp0.75 3h cost≤0.10 | 39 | 0.12 | 51.3 % | +0.009 | −0.089 [−0.34, +0.17] | 0.78 | 6.5 | −0.23 / +0.06 |
| E1 mid limit (prod) tp0.3 1h all | 183 | 0.56 | 21.9 % | −0.172 | −1.062 [−1.34, −0.79] | 0.03 | 194 | −2.42 / −0.59 |

* **≥ 70 % WR on TEST: 1 config of 120** (E3 tp0.3 3h cost≤0.10, 28 wins / 39) — a multiple-testing pick on n=39, still net −0.12 R
  (needs ≈ 80 %+ WR to break even at TP 0.3 R after costs). Its TRAIN WR was 69 % (n=81, net −0.13 R).
* **Profitable after fees: none.** 0/120 configs have a net CI above 0; all 112 configs with trades have a negative net avg R (8 E1 cost≤0.10 configs have 0 trades)
  (best −0.089 R). No config beats its random p95 with a positive net.
* The prod-like mid limit (E1) is the worst: WR 9–44 %, −0.54 to −1.81 R/trade — micro zones, fees ≈ a third of the risk.

## Verdict
Restricting to crypto M5 alerts between 15:00 and 17:00 Paris makes things worse, not better: too few trades (≤ 0.5/day) and
fees that eat the edge. Nothing here is a ≥ 70 % WR strategy that makes money; do not trade it.
