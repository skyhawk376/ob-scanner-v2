# OB shape study — summary (2026-10-09)

Question (Oscar): "le scanner m'envoie-t-il de faux OBs ? compare la forme des OBs invalidés vs validés".
Protocol: PREREG.md (textbook criteria + TRAIN/TEST split fixed before outcomes; candidate rules committed in 563d7ac
before TEST was computed). Detailed tables: REPORT_TABLES.md (analyze.py), detection checks: checks.md (checks.py).

## Samples
* Prod: 388 touched zones (all 7 TFs, snapshot 2026-10-08 ~10:00 Paris); 41 really alerted on Telegram (≥4★ Filtre B).
  Outcome "hold" (limit at entry filled, +2R before SL): 155 tp / 212 sl. Scanner status: 269 réaction / 117 échec.
  Alerted: 12 tp / 26 sl / 3 open.
* History: 21,894 touched ≥4★ zones, scanner-parity engine, 14 symbols, M5–H4, 2023-01 → 2026-09 (6,641 tp / 14,843 sl);
  realistic live sim: 14,102 TRAIN / 6,883 TEST trades.

## 1. Success vs failure shape
* History: no OB-shape feature separates winners from losers. All 30 pre-fill features have AUC in 0.485–0.523
  (0.5 = coin flip); medians nearly identical (e.g. FVG 0.33 vs 0.35 ATR, body ratio 0.38 vs 0.38, displacement 1.19 vs 1.21 ATR).
  Every bucket's +2R rate sits at 29–33 % (breakeven for 2R = 33 %).
* Prod (n=367): weak hints only, CIs touching/near 0.5: smaller impulse (AUC 0.39), smaller FVG (0.43, CI 0.375–0.486),
  quicker touch (0.42) do slightly *better* — i.e. the opposite of "big displacement = good OB" — and they do not
  replicate on the 21.9k history sample. zone_h_atr / prox wick separate the scanner *status* only, because zones > 1 ATR
  use the 50 % mid entry (deeper entry → status "réaction" more often: 86 % vs 63 %) — not a shape effect.
* Only after-fill info separates (touch candle closing through the zone = 0 % success), useless for entry.

## 2. Non-textbook zones (≥2 of T1–T8 failed)
* History 62.8 %, prod 70.4 %, alerted 22/41 (53.7 %). Main reasons: born in chop (T6, 58 % prod), wick-dominated OB
  candle body < 25 % (T7, 44 %), weak displacement < 1 ATR (T1, 44 %), FVG < 0.25 ATR (T2, 45 %).
* Performance: non-textbook are NOT worse. History +2R rate 31.1 % vs 30.7 %; prod 43 % vs 40 %; alerted 10/20 tp
  (trade_sim +0.20R avg, n=19) vs textbook 2/18 tp (−0.62R, n=15), Fisher p=0.015 (small n, opposite of hypothesis).
* Engine vs spec: 100 % of prod zones re-derive to the same OB candle, prices, BOS close, FVG and virgin rule — no
  wrong-candle/wrong-side bug. But by textbook standards: 16 % of OBs precede the broken pivot, 15 % have the leg extreme
  > 0.1 ATR beyond the distal edge (SL not behind the real swing), 24 zones' first displacement candle is counter-direction.

## 3. Pre-registered filters on TEST (realistic sim, per-asset costs; ALL TFs)
| rule | n | WR | gross R | net R [95 % CI] | vs random same size |
|---|---|---|---|---|---|
| baseline | 6883 | 28.8 % | −0.017 | −0.629 [−0.668, −0.590] | — |
| R1 textbook (tb_fails ≤ 1) | 2578 | 27.8 % | −0.067 | −0.680 [−0.747, −0.614] | worse than random (2nd pct) |
| R2 slow approach | 2619 | 30.4 % | −0.013 | −0.581 [−0.646, −0.516] | 96th pct |
| R3 cost_r ≤ 0.10 | 1605 | 34.8 % | +0.019 | −0.172 [−0.232, −0.112] | 100th pct |
| R2+R3 | 715 | 33.3 % | −0.030 | −0.205 [−0.292, −0.117] | 100th pct |
No rule passes the pre-registered bar (net > 0 with CI > 0). Only the cost filter beats random; textbook filtering hurts.
H1 TEST: baseline −0.18R net; all rules still ≤ −0.11R. H4 TEST baseline +0.08R net (n=42, CI −0.19..+0.35).

## Bugs / issues found
* "Réaction +2R" status while a resting limit at the alerted entry would have hit SL first: 95/269 prod (35 %), 46.6 % hist.
* Telegram text says "(milieu OB)" but zones ≤ 1 ATR use the OB open (33/41 alerted zones).
* 16/18 "Invalidation/SL" messages also say "entrée mid pas encore atteinte".
* Duplicate send: GBPAUD H1 bull 1.892–1.894 "réaction" sent 3×. 31/388 zones in overlapping same-side clusters
  (multi-TF duplicates of the same move, 8 alerted).
* Micro zones: FOREX M5 median risk 1.4 pips, 81 % < 3 pips → spread/commission ≫ edge (cost is the main loss driver).

Visuals: /workspace/ob_shape/winners_vs_losers.png, /workspace/ob_shape/features.png (plots.py; copies in results/).
