# Backtest OB 5★ Kasper-style (v2 engine, offline)

Generated: **2026-10-05 21:13 CEST** (Europe/Paris)

## Method

- Engine: `ob-scanner-v2-fly` `detect_zones` + `simulate_lifecycle` (branch always-on).
- OB = last opposite candle before impulse/BOS; stars = FVG / trend / Fib 0.5 / liquidity / session; virgin OB required at first causal sight.
- Entry = first return (wick intersect) to zone after OB+2; SL beyond OB (+ ATR buffer); TP = opposing liquidity **or** reaction metric (+1.0R); soft reaction **0.5R** ON.
- Filter: `min_score=5`, `require_fvg=True`, `require_fresh=True`, TF=`H1`.
- Causal walk-forward: expanding window; each `(direction, ts_ob)` taken once at first appearance; lifecycle then run on full series.
- Closed trades only for WR / avg R / expectancy / max DD. Outcomes `expiree` / still `active` / `touchee` at end of cache = open (excluded from WR).
- R attribution: `echec` = **-1R**; `reaction` = **+reaction_threshold_r** (soft min → often +0.5R when soft ON).
- No live fetch, no deploy, no invented fills.

## Cache coverage

- Cache dir: `/workspace/ob-scanner-v2/data/cache`
- Symbols scanned: **48** (with data: **48**)
- Global bar range (UTC): `2026-05-27 19:00:00+00:00` → `2026-10-05 18:00:00+00:00` (≈ 2026-05-27 21:00 CEST → 2026-10-05 20:00 CEST Paris)
- Bars/symbol: min=800, max=1300, median=800

| Group | Symbols w/ H1 |
|---|---:|
| CRYPTO | 15 |
| FOREX | 28 |
| METAUX | 5 |

## Totals

| Metric | Value |
|---|---|
| Signals (first sight) | 40 |
| Closed trades | 28 |
| Opens / timeouts | 12 |
| Wins | 25 |
| Losses | 3 |
| Win rate | 89.29% |
| Avg R / expectancy | 0.3393 |
| Sum R | 9.5000 |
| Max DD (R, cum.) | 1.0000 |
| Profit factor | 4.1667 |

## By group

| Group | Signals | Closed | WR | Avg R | Sum R | Max DD | Opens |
|---|---:|---:|---:|---:|---:|---:|---:|
| CRYPTO | 15 | 12 | 91.67% | 0.3750 | 4.5000 | 1.0000 | 3 |
| FOREX | 17 | 11 | 81.82% | 0.2273 | 2.5000 | 1.0000 | 6 |
| METAUX | 8 | 5 | 100.00% | 0.5000 | 2.5000 | 0.0000 | 3 |

## METAUX (priority) by symbol

| Symbol | Signals | Closed | WR | Avg R | Sum R | Opens |
|---|---:|---:|---:|---:|---:|---:|
| COPPER | 2 | 2 | 100.00% | 0.5000 | 1.0000 | 0 |
| XAGUSD | 0 | 0 | — | — | 0.0000 | 0 |
| XAUUSD | 4 | 3 | 100.00% | 0.5000 | 1.5000 | 1 |
| XPDUSD | 1 | 0 | — | — | 0.0000 | 1 |
| XPTUSD | 1 | 0 | — | — | 0.0000 | 1 |

## By score (at detection)

| Score | Signals | Closed | WR | Avg R | Sum R |
|---:|---:|---:|---:|---:|---:|
| 5 | 40 | 28 | 89.29% | 0.3393 | 9.5000 |

## By session label (OB / ★5)

| Session (OB) | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| London | 18 | 13 | 76.92% | 0.1538 | 2.0000 |
| NY | 22 | 15 | 100.00% | 0.5000 | 7.5000 |

## By touched session

| Touched session | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| London | 4 | 100.00% | 0.5000 | 2.0000 |
| NY | 5 | 60.00% | -0.1000 | -0.5000 |
| — | 19 | 94.74% | 0.4211 | 8.0000 |

## By direction

| Direction | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| bull | 22 | 17 | 94.12% | 0.4118 | 7.0000 |
| bear | 18 | 11 | 81.82% | 0.2273 | 2.5000 |

## Outcomes

| Outcome | Count |
|---|---:|
| active | 2 |
| echec | 3 |
| expiree | 10 |
| reaction | 25 |

## Caveats

- Short cache window (~weeks–months of H1, typically ~800 bars/symbol); not a multi-year study.
- Soft 0.5R ON credits winners at +0.5R while losers are -1R → need WR > ~67% for positive expectancy under this attribution.
- Same-bar SL vs reaction ambiguity: lifecycle checks SL before reaction on each bar (conservative).
- Fib / liquidity scored with data available at first causal sight (expanding window); live rescans can update scores.
- No costs, slippage, or spread modeled. Yahoo/OANDA/Binance cache quality varies by symbol.
- Historical v1 `backtest_5star.py` used a different star model (app.js port) and fixed RR TP — **not directly comparable**.

