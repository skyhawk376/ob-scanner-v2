# WR ≥ 70 % — crypto / M5 / 15:00–17:00 Paris — pre-registration

Written 2026-10-09 ~20:05 Paris, BEFORE any outcome of this subset (TRAIN or TEST) was computed. Only event counts were looked at.
Disclosure: the previous WR70 study (PREREG_WR70.md, REPORT.md) already showed pooled TEST results where crypto and M5 were
part of the "all" filter (crypto with M5 included was among the worst subsets on TRAIN). Nothing on this exact subset has been computed.

## Subset
* Same zones / events / simulator / costs / split as PREREG_WR70.md (`sim.py`, unchanged; BE not used).
* Symbols BTC, ETH, SOL; zone TF = M5; **alert time = first M1 touch t₀** (the moment the scanner alert fires / limit is placed,
  prod entry +3 min) with Europe/Paris local time (DST-aware, tz_convert) in **[15:00, 17:00)**. The trade may fill/exit after 17:00.
* Event counts (TRAIN / TEST, orders, before fill): E1 398 / 230, E2 ≈159 / 99, E3 249–301 / 133–163.
  Because of this small sample, the minimum TRAIN trade count of the selection rule is **100** (instead of 300).

## Grid (120 configs)
entry {E1 mid limit, E2 T3 retest limit, E3 sweep & reclaim} × TP {0.3, 0.5, 0.75, 1.0} R × time stop {1h, 3h}
× filter {all, cost ≤ 0.10 R (commission/risk), BTC only, ETH only, SOL only}.
Win = net R > 0. Same entry definitions as PREREG_WR70.md (3-min delay, fill required, SL-first, per-asset costs).

## Selection (TRAIN only)
Highest TRAIN net avg R among configs with TRAIN WR ≥ 72 % and ≥ 100 TRAIN trades. If none eligible: highest TRAIN WR with
≥ 100 trades, flagged. Selection committed before TEST.

## TEST (read once, all 120 configs reported)
n, trades/weekday, WR(net), gross R, net R [95 % CI], PF, max DD, avg hold, random baseline (same filled zones, market at
uniform random minute in [t₀, t₀ + hold], same SL price/TP multiple/hold/costs, 200 draws; mean, p95).
Because 120 configs are shown on TEST, any TEST-best config other than the TRAIN-selected one is a multiple-testing pick and
is labelled as such. Verdict: (a) WR ≥ 70 %; (b) profitable after fees = net R CI lower bound > 0; (c) net > random p95.
