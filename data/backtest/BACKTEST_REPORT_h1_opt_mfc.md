# Backtest OB 5★ — strategy optimization (before / after)

Generated: **2026-10-05 21:17 CEST** (Europe/Paris)

## Method

- Repo: `/workspace/ob-scanner-v2-fly` (branch `feat/always-on-fly`).
- Engine: `detect_zones` + `simulate_lifecycle`; script `scripts/backtest_5star_offline.py`.
- OB = last opposite candle before impulse/BOS; stars = FVG / trend / Fib0.5 / liquidity / session; virgin OB.
- Entry = first wick return into zone after OB+2; SL beyond OB (+0.05 ATR); TP = opposing liquidity **or** reaction metric.
- Causal walk-forward; closed only for WR / avg R / expectancy / max DD.
- R: `echec` = **-1R**; `reaction` = **+reaction_threshold_r** (soft ON → +0.5R; soft OFF → +1R).
- Same-bar: SL before reaction. No costs/slippage. Cache-only.

## Approved changes (this run)

1. **Soft reaction OFF** default (`ENABLE_SOFT_REACTION=false`) → exit at **+1R** / opposing liquidity.
2. **NQ100 off by default** in scan groups; UI can still enable.
3. **Default scan groups:** `METAUX,FOREX,CRYPTO` (`DEFAULT_SCAN_GROUPS`; ENERGIE optional).

## Cache coverage

- Cache: `/workspace/ob-scanner-v2/data/cache`
- Before universe: **115** symbols (all groups). After default: **48** (METAUX+FOREX+CRYPTO).
- Global bar range (UTC): `2026-04-22` → `2026-10-05` (short H1 window; not multi-year).

| Group | Symbols w/ H1 (after defaults) |
|---|---:|
| METAUX | 5 |
| FOREX | 28 |
| CRYPTO | 15 |

## Before → After (headline)

| Metric | BEFORE (soft 0.5R ON, all groups) | AFTER (soft OFF, METAUX+FOREX+CRYPTO) |
|---|---|---|
| Signals | 246 | 40 |
| Closed | 160 | 28 |
| Win rate | 58.13% | 85.71% |
| **Avg R / expectancy** | **-0.1281** | **0.7143** |
| Sum R | -20.5000 | 20.0000 |
| Max DD (R) | 28.0000 | 2.0000 |
| Profit factor | 0.6940 | 6.0000 |

**Δ expectancy:** -0.1281 → 0.7143 (**+0.8424 R**).

## Ablation matrix

| Config | Soft | Groups | Closed | WR | Avg R | Sum R | Max DD | PF |
|---|---|---|---:|---:|---:|---:|---:|---:|
| BEFORE | 0.5R ON | ALL (115) | 160 | 58.13% | -0.1281 | -20.5000 | 28.0000 | 0.6940 |
| soft OFF only | OFF (+1R) | ALL (115) | 160 | 57.50% | 0.1500 | 24.0000 | 12.0000 | 1.3529 |
| groups only | 0.5R ON | M+F+C (48) | 28 | 89.29% | 0.3393 | 9.5000 | 1.0000 | 4.1667 |
| AFTER (approved) | OFF (+1R) | M+F+C (48) | 28 | 85.71% | 0.7143 | 20.0000 | 2.0000 | 6.0000 |
| AFTER + ENERGIE | OFF (+1R) | M+F+C+E (53) | 30 | 80.00% | 0.6000 | 18.0000 | 3.0000 | 4.0000 |

Notes:
- Soft OFF alone flips all-groups expectancy from **-0.13R** to **+0.15R** (same detections).
- Dropping NQ100 (and ENERGIE) is the larger lift: NQ100 was ~130/160 closed with weak edge.
- ENERGIE optional: 2 closed at -1R each → dilutes M+F+C slightly (0.71 → 0.60 avg R).

## AFTER — by group (soft OFF, METAUX+FOREX+CRYPTO)

| Group | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| METAUX | 5 | 100.00% | 1.0000 | 5.0000 |
| FOREX | 11 | 81.82% | 0.6364 | 7.0000 |
| CRYPTO | 12 | 83.33% | 0.6667 | 8.0000 |

## BEFORE — by group (soft 0.5R ON, all)

| Group | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| CRYPTO | 12 | 91.67% | 0.3750 | 4.5000 |
| ENERGIE | 2 | 0.00% | -1.0000 | -2.0000 |
| FOREX | 11 | 81.82% | 0.2273 | 2.5000 |
| METAUX | 5 | 100.00% | 0.5000 | 2.5000 |
| NQ100 | 130 | 52.31% | -0.2154 | -28.0000 |

## Deploy / runtime defaults

- `ENABLE_SOFT_REACTION=false` (fly.toml + secrets)
- `DEFAULT_SCAN_GROUPS=METAUX,FOREX,CRYPTO`
- UI default chips: Métaux / Forex / Crypto (NQ100 & Énergie off; toggle to enable)
- Pipeline fetch/scan/refresh uses the same default groups (`group=ALL` for full universe)

## Artifacts

- This report: `BACKTEST_REPORT.md`
- BEFORE soft ON all: `data/backtest/summary_h1_soft05.json`, `trades_h1_soft05.csv`
- Soft OFF all: `data/backtest/summary_h1_hard1r.json`
- AFTER M+F+C soft OFF: `data/backtest/summary_h1_opt_mfc.json`, `trades_h1_opt_mfc.csv`
- M+F+C soft ON: `data/backtest/summary_h1_mfc_soft05.json`
- M+F+C+E soft OFF: `data/backtest/summary_h1_opt_mfce.json`

## Caveats

- Short H1 cache (~800 bars/symbol). Small closed sample after filter (n=28).
- No spread/commission/slippage. Not live trading advice.
- Soft ON pays +0.5R wins vs -1R losses → needs WR ≳ 67% under this attribution.

