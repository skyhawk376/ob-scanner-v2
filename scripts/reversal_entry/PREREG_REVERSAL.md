# Reversal-candle entry triggers — pre-registration

Written 2026-10-09 ~18:20 Paris, BEFORE any trigger outcome (TRAIN or TEST) was computed.
Question (Oscar): « il faut qu'il y ait une bougie de retournement avant de rentrer ».

## Sample / data
* Zones: `scripts/ob_shape/results/hist_zones.parquet` — 21,894 touched ≥4★ Filtre B zones (scanner-parity engine),
  14 symbols (XAU, XAG, 9 FX, BTC/ETH/SOL), TFs M5/M15/M30/H1/H4, 2023-01 → 2026-09. (D/W zones are not in the sample.)
* Prices: research M1 (`data/cache/strategy_research/m1`). Simulator + per-asset costs: `scripts/strategy_research/common.py`
  (fill required, M1 path, SL-first on ambiguous bars, spread + commission + slippage; market legs pay half-spread + slip).
* Split: **TRAIN = first touch < 2025-07-01, TEST = ≥ 2025-07-01** (same split as all previous studies; TEST was never used
  for any entry-trigger work — the earlier `explore_confirm_entry.py` used TRAIN only. The 2025-01 split was not used because
  2025-H1 was already explored as TRAIN in earlier studies). TEST is read once, after the selection below is committed.

## Common definitions (bull zone; bear symmetric)
* Zone [bot, top], distal = bot, zone SL = bot − 0.05 ATR (as prod). First touch t₀ = first M1 minute ≥ the TF touch bar with low ≤ top.
* Trigger TF: `same` = zone TF; `ltf` = one TF lower: M5→M1, M15→M5, M30→M15, H1→M15, H4→H1.
* Eligible candles: trigger-TF candles from the one containing t₀, whose close ≤ t₀ + W (the candle containing t₀ is always eligible,
  so same-TF H4/H1 zones can trigger on the touch candle). W = 1h (hold 1h) or 3h (hold 3h), paired.
* Invalidation: if an eligible candle closes below bot before a trigger → no trade.
* Every reversal candle must have low ≤ top (wicked into the zone) and close > bot.
* Entry for close-based triggers: **market at the open of the first M1 bar ≥ candle close + 3 min** (manual latency), costs applied.
* SL variants: `zone` = zone SL; `candle` = reversal candle low (engulfing: min low of the 2 candles; CHoCH: lowest low since t₀) − 0.05 ATR.
  Trade skipped if fill ≤ SL. TP = fill + 2R (R = fill − SL). Time stop = hold (1h or 3h) after fill.

## Triggers (grid = 36 configs + 2 info-only)
| family | rule | configs |
|---|---|---|
| T0 baseline | limit at prod entry (mid OB or OB open), live from t₀, expiry 25h | hold {1h,3h} = 2 (+ info: same with 3-min latency, 2) |
| T1 engulfing | c>o, prev c<prev o, c ≥ prev o, o ≤ prev c + 0.05 ATR, min(low,prev low) ≤ top | TF{same,ltf} × SL{zone,candle} × {1h,3h} = 8 |
| T2 pin bar | lower wick ≥ 2×body, close in upper third of range, range > 0 | 8 |
| T4 close-back | wick into zone and close > top (back outside the proximal edge) | 8 |
| T3 LTF CHoCH | on ltf: level = most recent confirmed 2/2 fractal swing high (confirmed by the previous bar, pivot within 50 ltf bars before t₀ or later); trigger = ltf close > level | entry{close-market, retest-limit at level until t₀+W} × SL{zone,swing} × {1h,3h} = 8 |

## Selection rule (TRAIN only)
* Per family: config with the best TRAIN **net** avg R among configs with ≥ 300 TRAIN trades (all TFs/assets pooled).
* "Best trigger" = family pick with the highest TRAIN net avg R. T0 comparison uses the T0 config with the same hold.

## Success bar (TEST, read once)
A family pick passes if **all** hold on TEST: (1) net avg R > 0 with 95 % CI (normal approx.) above 0;
(2) net avg R above the 95th percentile of 200 random-entry draws (same triggered zones, market entry at a uniformly random
minute in [t₀, t₀+W], same SL price, TP 2R, same hold, same costs); (3) net avg R > T0 (same hold).
Secondary (descriptive only, not part of the bar): same picks restricted to commission/risk ≤ 0.10 (the R3 cost filter);
breakdown by TF and asset group; alerts/day.
