# Backtest OB 5★ Kasper-style (v2 engine, offline)

Generated: **2026-10-05 20:54 CEST** (Europe/Paris)

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
- Symbols scanned: **5** (with data: **5**)
- Global bar range (UTC): `2026-08-14 18:00:00+00:00` → `2026-10-05 18:00:00+00:00` (≈ 2026-08-14 20:00 CEST → 2026-10-05 20:00 CEST Paris)
- Bars/symbol: min=800, max=800, median=800

| Group | Symbols w/ H1 |
|---|---:|
| METAUX | 5 |

## Totals

| Metric | Value |
|---|---|
| Signals (first sight) | 8 |
| Closed trades | 5 |
| Opens / timeouts | 3 |
| Wins | 5 |
| Losses | 0 |
| Win rate | 100.00% |
| Avg R / expectancy | 0.5000 |
| Sum R | 2.5000 |
| Max DD (R, cum.) | 0.0000 |
| Profit factor | ∞ |

## By group

| Group | Signals | Closed | WR | Avg R | Sum R | Max DD | Opens |
|---|---:|---:|---:|---:|---:|---:|---:|
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
| 5 | 8 | 5 | 100.00% | 0.5000 | 2.5000 |

## By session label (OB / ★5)

| Session (OB) | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| London | 5 | 3 | 100.00% | 0.5000 | 1.5000 |
| NY | 3 | 2 | 100.00% | 0.5000 | 1.0000 |

## By touched session

| Touched session | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| London | 2 | 100.00% | 0.5000 | 1.0000 |
| — | 3 | 100.00% | 0.5000 | 1.5000 |

## By direction

| Direction | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| bull | 3 | 2 | 100.00% | 0.5000 | 1.0000 |
| bear | 5 | 3 | 100.00% | 0.5000 | 1.5000 |

## Outcomes

| Outcome | Count |
|---|---:|
| active | 1 |
| expiree | 2 |
| reaction | 5 |

## Caveats

- Short cache window (~weeks–months of H1, typically ~800 bars/symbol); not a multi-year study.
- Soft 0.5R ON credits winners at +0.5R while losers are -1R → need WR > ~67% for positive expectancy under this attribution.
- Same-bar SL vs reaction ambiguity: lifecycle checks SL before reaction on each bar (conservative).
- Fib / liquidity scored with data available at first causal sight (expanding window); live rescans can update scores.
- No costs, slippage, or spread modeled. Yahoo/OANDA/Binance cache quality varies by symbol.
- Historical v1 `backtest_5star.py` used a different star model (app.js port) and fixed RR TP — **not directly comparable**.

