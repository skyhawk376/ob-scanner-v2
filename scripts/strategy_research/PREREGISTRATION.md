# Pre-registration — strategy research (written BEFORE any backtest result was looked at)

Committed 2026-10-06 11:02 CEST (commit 8b8dbe5), before any grid was run (first grid output 11:06 CEST). Data: M1 2023-01-02 → 2026-09-30 (HistData = Dukascopy BID M1 for FX/metals/indices; Binance spot M1 for crypto).

## Split
* TRAIN: fills before 2025-07-01 00:00 UTC (~2.5 years). TEST: fills 2025-07-01 → 2026-09-30 (~15 months).
* All parameter choices, family winners and the final pick use TRAIN only. TEST is only read for the frozen selections.

## Execution model (all families)
* Signals use only closed bars (indicators "as of" last closed bar). Manual delay: an alert becomes an order 3 minutes
  after the signal bar close (market orders fill at the open of that minute + half-spread + slippage; pending
  limit/stop orders are only live from that minute). Delay sensitivity 1 / 5 min reported for winners.
* Fills on M1 bars; limit needs trade-through by half-spread; same-bar SL/TP -> SL; on the fill bar TP only on a close beyond.
* Costs per asset in `common.costs` (spread + commission + slippage per stop/market leg). Ranking uses net R at 1x costs.
  Winners are also reported at 1.5x and 2x costs.
* One position per signal; time stop 60 min after fill (main). 120/240 min reported as info only, never used to rank.

## Families and grids (compact)
A. OB 5★ (repo engine, causal walk-forward H1): min score {4,5} × trend filter {none, D1 EMA20, H4 EMA50}
   × TP {1R,2R} × fill window {any, 08:00-18:00 Paris} × basket {MFC (metals+forex+crypto = Filtre B), ALL} = 48.
   Entry = engine mid limit, SL = engine (distal + 0.05 ATR), order live 24h after detection.
B. Session liquidity sweep reversal: window {LON 08:00-11:00 on EU basket, NY 14:30-17:00 on US basket}
   × entry {market after M5 reclaim close, limit back at the swept level} × TP {1R, 2R, range mid} = 12.
   Range = 00:00-08:00 Paris (LON) or 00:00-14:30 Paris (NY). SL = sweep extreme + 0.1 ATR(H1). 1 trade/asset/day/window.
C. Opening-range breakout: open {EU 08:00 Paris, EU 09:00 Paris, NY 09:30 New York} × range {15,30 min}
   × SL {opposite side, range mid} × TP {1R,2R} × filter {none, D1 EMA20 direction} = 48. Stop orders at range
   high/low (OCO), live from range end + 3 min, expire 120 min after range end.
D. FVG retest in trend (M15): window/basket {EU 08:00-12:00, US 14:30-18:00} × trend {H1 EMA50, H4 EMA50}
   × entry {proximal edge, mid} × SL {gap far edge, first-candle extreme} (+0.1 ATR(M15)) × TP {1R,2R} = 32.
   FVG size >= 0.3 ATR(M15); first FVG per asset/window/day; limit live 120 min.
E. Baselines: previous-day high/low {fade (limit), breakout (stop)} × window {EU, US} × TP {1R,2R} = 8,
   SL = 1 ATR(H1). Plus a random-entry cost baseline (not ranked).
Baskets: EU = EURUSD, GBPUSD, EURGBP, EURJPY, GBPJPY, DAX, XAUUSD. US = XAUUSD, XAGUSD, EURUSD, USDCAD, NAS100, US500, BTC, ETH.
ALL = 17 symbols (EU ∪ US ∪ USDJPY, AUDUSD, USDCHF, SOL). WTI dropped (HistData gap 2024-01 → 2026-05).

Total ranked configs K = 148 (+ any "first signal of the day" volume variant, counted if used).

## Ranking rule
1. Eligible on TRAIN: n >= 150 and 0.5 <= trades/weekday <= 3.0.
2. Score = TRAIN t-statistic of mean net R (mean / standard error).
3. Family winner = highest score per family. If a winner trades > 2/weekday, its "first signal of the day
   (portfolio-wide)" variant is also evaluated (TRAIN-selected the same way, counted in K).
4. Recommended strategy = family winner with the highest TRAIN score whose TEST mean net R > 0.

## Robustness verdict (on TEST, frozen config)
* ROBUST only if: TEST mean net R > 0 with 95% CI lower bound > 0, still > 0 at 1.5x costs, and >= 3 of 5 TEST quarters > 0.
* PROMISING / near-miss: TEST mean > 0 but CI includes 0.
* Multiple testing: with K≈148 configs, a Bonferroni two-sided 5% bar needs |t| > ~3.4 on TRAIN; reported.

## Clarifications / deviations (logged after the runs, 2026-10-06 ~11:25 CEST)
1. Volume rule: base configs on 7-8-symbol baskets trade 2.5-7/weekday, so most were ineligible (> 3/wd). Following
   rule 3, every config with > 2 trades/weekday was ALSO evaluated as its "first fill of the day (portfolio-wide)"
   variant (`|fod`). These variants were added to the pool before selection -> K = 248 configs (148 base + 100 fod).
   Bonferroni bar becomes |t| > 3.72.
2. No minimum-risk floor was applied (considered after seeing B_SWEEP market-entry outliers, NOT applied, to stay
   with the pre-registered rules). Consequence: B_SWEEP market entries have a fat left tail from tiny stops.
3. Exploratory, NOT pre-registered: X1 US-index intraday momentum (scripts/strategy_research/exploratory.py),
   run after the grid failed. Reported separately, cannot be used as evidence.
4. Simulator sanity check added: random entries (random_baseline.py).
