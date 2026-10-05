# Backtest OB 5★ Kasper-style (v2 engine, offline)

Generated: **2026-10-05 20:57 CEST** (Europe/Paris)

## Method

- Repo: `/workspace/ob-scanner-v2-fly` (branch `feat/always-on-fly`).
- Engine: `backend/app/engine/detect.py` (`detect_zones`) + `backend/app/core/lifecycle.py` (`simulate_lifecycle`).
- Script: `scripts/backtest_5star_offline.py` (new offline walker; reuses v2 rules, not v1 `backtest_5star.py`).
- OB = last opposite candle before impulse/BOS; stars = FVG / trend / Fib0.5 / liquidity / session; **virgin OB** at first causal sight.
- Entry = first wick return into zone after OB+2; SL beyond OB (+0.05 ATR buffer); TP = opposing liquidity **or** reaction metric.
- **Primary config (current code):** soft reaction **0.5R ON**, primary reaction 1.0R, `min_score=5`, TF=H1, `require_fvg=True`, `require_fresh=True`.
- Causal walk-forward: expanding window; each `(direction, ts_ob)` once; lifecycle on full series.
- Closed only for WR / avg R / expectancy / max DD. `expiree` / end-of-cache `active`|`touchee` = open (excluded).
- R attribution: `echec` = **-1R**; `reaction` = **+reaction_threshold_r** (with soft ON → typically **+0.5R**).
- Same-bar: lifecycle evaluates **SL before** reaction (conservative).
- No live fetch, no deploy, no costs/slippage, **no invented numbers**.

## Cache coverage

- Cache dir: `/workspace/ob-scanner-v2/data/cache` (v2 cache; fly `data/cache` was empty).
- Symbols scanned: **115** (with H1 data: **115**).
- Global bar range (UTC): `2026-04-22 16:30:00+00:00` → `2026-10-05 18:00:00+00:00`
- Paris: 2026-04-22 18:30 CEST → 2026-10-05 20:00 CEST
- Bars/symbol: min=800, max=1300, median=800

| Group | Symbols w/ H1 |
|---|---:|
| CRYPTO | 15 |
| ENERGIE | 5 |
| FOREX | 28 |
| METAUX | 5 |
| NQ100 | 62 |

## Totals — primary (soft 0.5R ON)

| Metric | Value |
|---|---|
| Signals (first sight) | 246 |
| Closed trades | 160 |
| Opens / timeouts | 86 |
| Wins | 93 |
| Losses | 67 |
| Win rate | 58.13% |
| Avg R / expectancy | -0.1281 |
| Sum R | -20.5000 |
| Max DD (R, cum.) | 28.0000 |
| Profit factor | 0.6940 |

## Comparison — soft OFF (+1R reaction only)

Same signals/detections; lifecycle with `soft_reaction_r=0` (reaction at +1R or TP1).

| Metric | soft 0.5R ON | soft OFF (+1R) |
|---|---|---|
| Closed | 160 | 160 |
| Win rate | 58.13% | 57.50% |
| Avg R | -0.1281 | 0.1500 |
| Sum R | -20.5000 | 24.0000 |
| Max DD (R) | 28.0000 | 12.0000 |
| Profit factor | 0.6940 | 1.3529 |

Note: soft ON pays winners **+0.5R** vs losers **-1R** → needs WR ≳ 67% for positive expectancy under this attribution. Soft OFF pays **+1R** / **-1R**.

## By group (soft 0.5R ON)

| Group | Signals | Closed | WR | Avg R | Sum R | Max DD | Opens |
|---|---:|---:|---:|---:|---:|---:|---:|
| CRYPTO | 15 | 12 | 91.67% | 0.3750 | 4.5000 | 1.0000 | 3 |
| ENERGIE | 3 | 2 | 0.00% | -1.0000 | -2.0000 | 2.0000 | 1 |
| FOREX | 17 | 11 | 81.82% | 0.2273 | 2.5000 | 1.0000 | 6 |
| METAUX | 8 | 5 | 100.00% | 0.5000 | 2.5000 | 0.0000 | 3 |
| NQ100 | 203 | 130 | 52.31% | -0.2154 | -28.0000 | 31.0000 | 73 |

## METAUX (priority) by symbol — soft 0.5R ON

| Symbol | Signals | Closed | WR | Avg R | Sum R | Opens |
|---|---:|---:|---:|---:|---:|---:|
| COPPER | 2 | 2 | 100.00% | 0.5000 | 1.0000 | 0 |
| XAGUSD | 0 | 0 | — | — | 0.0000 | 0 |
| XAUUSD | 4 | 3 | 100.00% | 0.5000 | 1.5000 | 1 |
| XPDUSD | 1 | 0 | — | — | 0.0000 | 1 |
| XPTUSD | 1 | 0 | — | — | 0.0000 | 1 |

### METAUX — soft OFF (+1R)

| Symbol | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| COPPER | 2 | 100.00% | 1.0000 | 2.0000 |
| XAGUSD | 0 | — | — | 0.0000 |
| XAUUSD | 3 | 100.00% | 1.0000 | 3.0000 |
| XPDUSD | 0 | — | — | 0.0000 |
| XPTUSD | 0 | — | — | 0.0000 |

## By score (at detection) — soft 0.5R ON

| Score | Signals | Closed | WR | Avg R | Sum R |
|---:|---:|---:|---:|---:|---:|
| 5 | 246 | 160 | 58.13% | -0.1281 | -20.5000 |

## By session label (OB / ★5) — soft 0.5R ON

| Session (OB) | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| London | 20 | 14 | 71.43% | 0.0714 | 1.0000 |
| NY | 226 | 146 | 56.85% | -0.1473 | -21.5000 |

## By touched session — soft 0.5R ON

| Touched session | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| London | 6 | 66.67% | 0.0000 | 0.0000 |
| NY | 97 | 40.21% | -0.3969 | -38.5000 |
| — | 57 | 87.72% | 0.3158 | 18.0000 |

## By direction — soft 0.5R ON

| Direction | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| bull | 143 | 92 | 61.96% | -0.0707 | -6.5000 |
| bear | 103 | 68 | 52.94% | -0.2059 | -14.0000 |

## Outcomes — soft 0.5R ON

| Outcome | Count |
|---|---:|
| active | 11 |
| echec | 67 |
| expiree | 75 |
| reaction | 93 |

## Symbols with ≥3 closed (soft 0.5R) — by Sum R

| Symbol | Group | Closed | WR | Avg R | Sum R |
|---|---|---:|---:|---:|---:|
| AVGO | NQ100 | 3 | 100.00% | 0.5000 | 1.5000 |
| XAUUSD | METAUX | 3 | 100.00% | 0.5000 | 1.5000 |
| NFLX | NQ100 | 5 | 80.00% | 0.2000 | 1.0000 |
| GILD | NQ100 | 4 | 75.00% | 0.1250 | 0.5000 |
| MRVL | NQ100 | 4 | 75.00% | 0.1250 | 0.5000 |
| PDD | NQ100 | 4 | 75.00% | 0.1250 | 0.5000 |
| CDNS | NQ100 | 3 | 66.67% | 0.0000 | 0.0000 |
| MDLZ | NQ100 | 3 | 66.67% | 0.0000 | 0.0000 |
| QCOM | NQ100 | 3 | 66.67% | 0.0000 | 0.0000 |
| REGN | NQ100 | 3 | 66.67% | 0.0000 | 0.0000 |
| MELI | NQ100 | 5 | 60.00% | -0.1000 | -0.5000 |
| LRCX | NQ100 | 4 | 50.00% | -0.2500 | -1.0000 |
| NVDA | NQ100 | 4 | 50.00% | -0.2500 | -1.0000 |
| AMAT | NQ100 | 3 | 33.33% | -0.5000 | -1.5000 |
| AMD | NQ100 | 3 | 33.33% | -0.5000 | -1.5000 |
| … | | | | | |
| TXN | NQ100 | 3 | 33.33% | -0.5000 | -1.5000 |
| AMZN | NQ100 | 5 | 40.00% | -0.4000 | -2.0000 |
| ASML | NQ100 | 4 | 25.00% | -0.6250 | -2.5000 |
| ADSK | NQ100 | 3 | 0.00% | -1.0000 | -3.0000 |
| VRTX | NQ100 | 3 | 0.00% | -1.0000 | -3.0000 |

## Artifacts

- Primary report: `BACKTEST_REPORT.md` (this file)
- Soft ON CSV: `data/backtest/trades_h1_soft05.csv`
- Soft ON JSON: `data/backtest/summary_h1_soft05.json`
- Soft OFF CSV: `data/backtest/trades_h1_hard1r.csv`
- Soft OFF JSON: `data/backtest/summary_h1_hard1r.json`
- Runner: `scripts/backtest_5star_offline.py`

## Caveats

- Short H1 cache (~800 bars/symbol; roughly mid-Aug→05 Oct 2026 for many names; some series start earlier in 2026). **Not** a multi-year backtest.
- Soft 0.5R ON credits +0.5R wins vs -1R losses → negative expectancy here despite ~58% WR.
- Soft OFF (+1R) shows modestly positive avg R on the **same** detections — still a small sample.
- Fib/liquidity scored at first causal sight; live rescans can change scores.
- No spread/commission/slippage. Provider cache quality varies.
- v1 `ob-scanner/backtest_5star.py` used a different star model (app.js) + fixed RR — **not comparable** to these figures.
- Do not treat as live trading advice.

