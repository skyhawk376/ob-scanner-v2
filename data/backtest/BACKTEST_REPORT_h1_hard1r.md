# Backtest OB 5★ Kasper-style (v2 engine, offline)

Generated: **2026-10-05 21:16 CEST** (Europe/Paris)

## Method

- Engine: `ob-scanner-v2-fly` `detect_zones` + `simulate_lifecycle` (branch always-on).
- OB = last opposite candle before impulse/BOS; stars = FVG / trend / Fib 0.5 / liquidity / session; virgin OB required at first causal sight.
- Entry = first return (wick intersect) to zone after OB+2; SL beyond OB (+ ATR buffer); TP = opposing liquidity **or** reaction metric (+1.0R); soft reaction **0.0R** OFF.
- Filter: `min_score=5`, `require_fvg=True`, `require_fresh=True`, TF=`H1`.
- Causal walk-forward: expanding window; each `(direction, ts_ob)` taken once at first appearance; lifecycle then run on full series.
- Closed trades only for WR / avg R / expectancy / max DD. Outcomes `expiree` / still `active` / `touchee` at end of cache = open (excluded from WR).
- R attribution: `echec` = **-1R**; `reaction` = **+reaction_threshold_r** (soft min → often +0.0R when soft ON).
- No live fetch, no deploy, no invented fills.

## Cache coverage

- Cache dir: `/workspace/ob-scanner-v2/data/cache`
- Symbols scanned: **115** (with data: **115**)
- Global bar range (UTC): `2026-04-22 16:30:00+00:00` → `2026-10-05 18:00:00+00:00` (≈ 2026-04-22 18:30 CEST → 2026-10-05 20:00 CEST Paris)
- Bars/symbol: min=800, max=1300, median=800

| Group | Symbols w/ H1 |
|---|---:|
| CRYPTO | 15 |
| ENERGIE | 5 |
| FOREX | 28 |
| METAUX | 5 |
| NQ100 | 62 |

## Totals

| Metric | Value |
|---|---|
| Signals (first sight) | 246 |
| Closed trades | 160 |
| Opens / timeouts | 86 |
| Wins | 92 |
| Losses | 68 |
| Win rate | 57.50% |
| Avg R / expectancy | 0.1500 |
| Sum R | 24.0000 |
| Max DD (R, cum.) | 12.0000 |
| Profit factor | 1.3529 |

## By group

| Group | Signals | Closed | WR | Avg R | Sum R | Max DD | Opens |
|---|---:|---:|---:|---:|---:|---:|---:|
| CRYPTO | 15 | 12 | 83.33% | 0.6667 | 8.0000 | 1.0000 | 3 |
| ENERGIE | 3 | 2 | 0.00% | -1.0000 | -2.0000 | 2.0000 | 1 |
| FOREX | 17 | 11 | 81.82% | 0.6364 | 7.0000 | 1.0000 | 6 |
| METAUX | 8 | 5 | 100.00% | 1.0000 | 5.0000 | 0.0000 | 3 |
| NQ100 | 203 | 130 | 52.31% | 0.0462 | 6.0000 | 15.0000 | 73 |

## METAUX (priority) by symbol

| Symbol | Signals | Closed | WR | Avg R | Sum R | Opens |
|---|---:|---:|---:|---:|---:|---:|
| COPPER | 2 | 2 | 100.00% | 1.0000 | 2.0000 | 0 |
| XAGUSD | 0 | 0 | — | — | 0.0000 | 0 |
| XAUUSD | 4 | 3 | 100.00% | 1.0000 | 3.0000 | 1 |
| XPDUSD | 1 | 0 | — | — | 0.0000 | 1 |
| XPTUSD | 1 | 0 | — | — | 0.0000 | 1 |

## By score (at detection)

| Score | Signals | Closed | WR | Avg R | Sum R |
|---:|---:|---:|---:|---:|---:|
| 5 | 246 | 160 | 57.50% | 0.1500 | 24.0000 |

## By session label (OB / ★5)

| Session (OB) | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| London | 20 | 14 | 71.43% | 0.4286 | 6.0000 |
| NY | 226 | 146 | 56.16% | 0.1233 | 18.0000 |

## By touched session

| Touched session | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| London | 6 | 66.67% | 0.3333 | 2.0000 |
| NY | 97 | 40.21% | -0.1959 | -19.0000 |
| — | 57 | 85.96% | 0.7193 | 41.0000 |

## By direction

| Direction | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| bull | 143 | 92 | 60.87% | 0.2174 | 20.0000 |
| bear | 103 | 68 | 52.94% | 0.0588 | 4.0000 |

## Outcomes

| Outcome | Count |
|---|---:|
| active | 11 |
| echec | 68 |
| expiree | 75 |
| reaction | 92 |

## Caveats

- Short cache window (~weeks–months of H1, typically ~800 bars/symbol); not a multi-year study.
- Soft 0.5R ON credits winners at +0.5R while losers are -1R → need WR > ~67% for positive expectancy under this attribution.
- Same-bar SL vs reaction ambiguity: lifecycle checks SL before reaction on each bar (conservative).
- Fib / liquidity scored with data available at first causal sight (expanding window); live rescans can update scores.
- No costs, slippage, or spread modeled. Yahoo/OANDA/Binance cache quality varies by symbol.
- Historical v1 `backtest_5star.py` used a different star model (app.js port) and fixed RR TP — **not directly comparable**.

