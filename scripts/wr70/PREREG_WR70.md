# WR ≥ 70 % OB strategy — pre-registration

Written 2026-10-09 ~19:25 Paris, BEFORE any outcome of this grid (TRAIN or TEST) was computed.
Question (Oscar): « Fait une stratégie avec minimum 70 % de wr, propose ». OB-only (no other setups).

## Honest prior (math, before data)
A win rate ≥ 70 % needs TP closer than SL. With TP = k·R and no edge, the breakeven WR is 1/(1+k) **before costs**:
k=0.3 → 76.9 %, 0.5 → 66.7 %, 0.75 → 57.1 %, 1.0 → 50 %. Costs are paid in R on every trade and do not shrink with TP,
so small TPs need an even higher WR (e.g. cost 0.10 R at k=0.3 → breakeven ≈ 84.6 %). High WR ≠ profit; the report must
show net expectancy.
Disclosure: earlier studies (ob_shape, reversal_entry) already showed TEST results of the same zones at TP 2R
(T0 net −0.63 R, T3 −0.27 R, T5a −0.32 R; WR 28–37 %). No TEST outcome at TP < 2R has been computed.

## Sample / simulator (unchanged from reversal_entry)
* Zones: `scripts/ob_shape/results/hist_zones.parquet` — 21,894 touched ≥4★ Filtre B zones, 14 symbols
  (XAU, XAG, 9 FX, BTC/ETH/SOL), M5/M15/M30/H1/H4, 2023-01 → 2026-09.
* Entry events: `scripts/reversal_entry/results/events.parquet` (already built, outcome-free order definitions).
* Split: TRAIN = first touch t₀ < 2025-07-01, TEST = t₀ ≥ 2025-07-01. TEST read once, after `selection.json` is committed.
* Simulator: same rules as `scripts/strategy_research/common.py` (fill must actually happen with spread, M1 path,
  SL-first on any ambiguous bar, TP on the fill bar only if the bar closes beyond it, per-asset spread+commission+slippage,
  time stop at market). Re-implemented in `scripts/wr70/sim.py` only to add the optional break-even; with BE off it must
  reproduce `common.simulate` exactly (checked on TRAIN before the grid). Orders whose fill is at/through the SL are dropped.
* Win = **net R > 0** (after costs). R = planned risk |entry level − SL| (limit/stop orders).

## Entries (bull; bear symmetric)
* **E1 mid limit** = prod entry (mid OB if zone > 1 ATR else OB open), resting limit live from t₀ + 3 min (manual delay),
  expiry 25 h, SL = zone SL (distal − 0.05 ATR). (`T0lat|limit|zone`)
* **E2 T3 retest limit** = lower-TF CHoCH (close above last confirmed 2/2 fractal swing high), then limit at that swing level
  from trigger close + 3 min until t₀ + W, SL = zone SL. (`T3|retest|zone|{W}`)
* **E3 sweep & reclaim** = after an M1 low beyond zone SL within t₀+W, buy stop at the prod entry live from sweep + 3 min,
  fill ≤ t₀ + W, SL = sweep extreme − 0.05 ATR. (`T5a|m1|sweep|{W}`)
* W (trigger window) = time stop (1h ↔ W=1h events, 3h ↔ W=3h events).

## Grid
**Stage A (60 configs)**: entry {E1, E2, E3} × TP {0.3, 0.5, 0.75, 1.0} R × filter {all, no M5, no crypto,
cost ≤ 0.10 R (commission/risk), H1+H4 only}; time stop 1 h (Oscar's real holding), no BE.
**Stage B (≤ 15 configs, TRAIN only)**: for the 5 best stage-A configs by the selection metric below (eligible ones first,
then by TRAIN WR if fewer than 5 are eligible): + time stop 3 h; + BE 1 h; + BE 3 h.
BE = once the M1 high reaches entry + 0.5·TP·R, the stop moves (from the next bar) to entry + commission (net ≈ 0, a BE
exit counts as a loss if net ≤ 0).
Total ≤ 75 configs, all evaluated on TRAIN only.

## Selection rule (TRAIN)
Among stage A ∪ B configs with **TRAIN WR(net) ≥ 72 % and ≥ 300 TRAIN trades**, pick the highest TRAIN **net avg R**.
Report also the next 4 best eligible (top-5 TRAIN candidates). If none is eligible, pick the config with the highest TRAIN WR
among those with ≥ 300 trades and flag it as not meeting the bar.

## TEST (read once) — what is reported
For the selected + top-5 TRAIN candidates: n, trades/weekday, WR(net), avg R gross, avg R net [95 % CI normal approx.],
PF, max DD (R), avg hold, and a random-entry baseline (same filled zones, market entry at a uniform random minute in
[t₀, t₀ + W], same SL price, same TP multiple, same time stop, same costs; 200 draws; mean and p95).
Breakdown of the selected config by TF and asset group.
Verdict criteria (TEST): (a) WR ≥ 70 %; (b) **profitable after costs** = net avg R > 0 with 95 % CI lower bound > 0;
(c) edge vs random = net > random p95. A strategy is only proposed as "tradable" if (a) and (b) hold.
