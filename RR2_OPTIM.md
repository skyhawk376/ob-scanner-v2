# RR-2 optimisation — Filtre B (research only, no deploy)

Generated: **2026-10-06 10:14 CEST** (Europe/Paris). Branch `feat/always-on-fly`. Nothing deployed, Fly untouched.

Scripts: `scripts/rr2_optim_backtest.py` (detection + grid), `scripts/rr2_report.py` (this report), `scripts/fetch_binance_m15.py` (Binance 15m klines for crypto intrabar paths). Same H1 cache (`/workspace/ob-scanner-v2/data/cache`), same engine (`detect_zones`, causal walk-forward, virgin OB + FVG, min 4★, METAUX+FOREX+CRYPTO, 48 symbols) as `volume_options_backtest.py`.

## TL;DR

**Key table** (hold 1h, ≥4★, METAUX+FOREX+CRYPTO; "realistic" = mid limit order must actually fill, M15 price path, every trade closed by TP / SL / 1h time stop; no costs unless stated)

| Config | Trades | /weekday | WR | Avg R | PF | MaxDD R | IS → OOS avg R |
|---|---:|---:|---:|---:|---:|---:|---|
| Live B +1R, old method (reproduced) | 92 | 1.03 (really 3.28) | 83.7% | +0.674 | 5.13 | 3.0 | — |
| Plain B +2R, old method (reproduced) | 64 | 0.72 (really 2.26) | 76.6% | +1.297 | 6.53 | 4.0 | — |
| **Live B +1R, realistic** | 88 | 3.30 | 55.7% | **+0.104** [-0.07, +0.28] | 1.31 | 6.2 | -0.008 → +0.217 |
| **Plain B +2R, realistic** | 88 | 3.30 | 51.1% | **+0.142** [-0.07, +0.35] | 1.39 | 5.0 | +0.074 → +0.210 |
| B +2R + Lon+NY + BE@+1R (≈1–1.5/day) | 41 | 1.44 | 46.3% | +0.205 [-0.13, +0.55] | 1.56 | 7.1 | +0.107 → +0.308 |
| Grid best 1h: 75%-depth limit, SL distal+0.1ATR, BE@+1R, TP 2R | 78 | 2.94 | 41.0% | +0.325 [+0.02, +0.63] | 1.72 | 5.0 | +0.494 → +0.128 |

Findings:

1. **The old numbers reproduce exactly but are inflated.** Three accounting artifacts plus a volume miscount (quantified in §1–§2):
   - *Phantom mid fill*: live/lifecycle manages a mid-entry trade from the **first zone contact** (`require_entry_fill=False` for mid). On the M15 path, only 38/92 zones actually trade the mid at the touch, and those average **-0.07R** (B +2R, 1h). The other 54 average +1.18R in the live accounting, mostly bounces off the zone edge that a mid limit never caught. When the mid limit really fills (later), they average +0.30R (n=50).
   - *H1 same-bar ordering*: on the touch bar, the H1 high/low is often printed **before** price reached the zone. On M15 the live-accounting B +1R drops from +0.628 to +0.502R.
   - *Dropped timeouts*: the old method **excluded** trades that didn't finish within the touch bar (5 at +1R, **33 at +2R**) instead of closing them at the time stop. That is the main reason the earlier +2R test showed +1.30R. Closing them at the 1h time stop on H1 already gives +0.992R.
   - *Volume*: the "~1 trade/weekday" comes from dividing by a 124.7-day span that only TON has. All 48 symbols are only live for about 6 weeks (crypto about 4), and the real flow of B is **≈3.3 filled trades/weekday** (≈3.3 even with the old accounting).
2. **RR2 vs RR1 (same entry, SL, and 1h hold): +2R is ≥ +1R in every model** (realistic: legacy H1 +0.333 vs +0.332 = tie, cons H1 +0.119 vs +0.027, M15 +0.142 vs +0.104), and on M15 +2R is positive in both halves (+1R is not). But the gain is small (+0.038R/trade on M15), and both 95% CIs include 0. Over 1h the +2R target is rarely reached: TP 9, SL 28, time stop 51 of 88. RR2 at 1h is effectively "SL or exit at market after 1h, with a rare +2R".
3. **Best grid variant at 1h** = 75%-depth limit (deep in the zone, tighter stop), SL distal+0.1 ATR, BE (or 50% partial) at +1R: about +0.32R, PF ≈1.7. It is **not robust**: IS +0.49 → OOS +0.13. CRYPTO carries it (+0.69R, n=28) while METAUX is about 0. With one trade per day the OOS turns negative (-0.69R). Its neighbour d50 (pure mid) is ≈0, which looks like noise, not structure.
4. **About 1 trade/day at 1h**: the London+NY filter on the fill time halves the volume to 1.44/weekday. B +2R then gives +0.173R (BE@+1R +0.205, partial +0.211) vs +0.120 at +1R, positive in both halves for +2R. But n=41, and CRYPTO (n=8) supplies most of the R. 5★ only (0.88/weekday) is **negative** (-0.061R, n=23). "First fill of the day" has a negative OOS (-0.207R).

## Recommendation

- **RR2 is directionally better than live B +1R for about 1h holds**, but only modestly and without statistical confirmation. Realistic expectancy is about +0.10 to +0.20R/trade before costs, with WR about 45–55%. It is not 77–84%.
- If you change anything, the **least-overfit RR2 setup** is **plain B +2R**: keep the mid entry, SL distal+0.05 ATR, ≥4★, M+F+C, and 1h time stop. To get to about 1–1.5 trades/weekday, optionally take only fills in **London/NY** and move the SL to **break-even at +1R**. Both are mild, interpretable filters that stay positive in both halves.
- **Do not adopt the 75%-depth entry** (or any grid "winner") yet. Paper-trade it alongside.
- **Fix the measurement before trusting live stats** (not done here, research only). With `require_entry_fill=False` for mid, the live "Réaction +1R" alerts and the 84% WR count phantom fills, and timeouts are not closed. Any live-vs-backtest comparison will look much better than real fills.
- Re-run on a longer history (≥6 months of H1 + M15) before any production change. With about 80–90 trades over about 6 weeks, a ±0.3R confidence interval cannot separate these variants.


## 1. Calibration — exact reproduction of the old method

Old method = `simulate_lifecycle` (mid entry managed from first zone contact, H1 OHLC, SL checked first), hold ≤1 H1 bar, **trades not resolved on the touch bar are dropped** (not closed at a time stop), trades/weekday = closed / (touch span × 5/7).

| | Signals | Closed | W / L | WR | Avg R | Sum R | Dropped (hold-capped) | Trades/weekday (old span) | Trades/weekday (per-group window) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B +1R | 142 | 92 | 77 / 15 | 83.7% | 0.674 | 62.0 | 5 | 1.03 | 3.28 |
| B +2R | 142 | 64 | 49 / 15 | 76.6% | 1.297 | 83.0 | 33 | 0.72 | 2.26 |

Both match the existing reports exactly (92 / 83.7% / +0.674R and 64 / 76.6% / +1.297R).

### Volume correction

The old "~1 trade/weekday" divides by a 124.7-day touch span that comes from **TON only** (1 300 H1 bars back to May). Every other symbol has 800 H1 bars, so after the 80-bar warm-up the 48-symbol universe is only live from:

| Group | Window (UTC) | Weekdays |
|---|---|---:|
| METAUX | 2026-08-20 09:00 → 2026-10-05 18:00 | 33.1 |
| FOREX | 2026-08-24 14:00 → 2026-10-05 18:00 | 30.1 |
| CRYPTO | 2026-09-05 19:00 → 2026-10-05 08:00 | 21.1 |

Trades/weekday below = Σ_group (trades in the group window / weekdays of that window). Crypto weekend trades count in the numerator (same as the old convention). TON trades before the crypto window are excluded. Halves: each group window is split at its midpoint (IS = first half, OOS = second half).

## 2. Where the old numbers come from — accounting decomposition (≥4★, all sessions, SL distal+0.05ATR, hold 1h)

Every trade is now **closed** (TP, SL, or time stop at the close of the last hold bar). Models: `legacy` = H1 high/low incl. the entry bar; `cons` = H1, but on the entry bar TP/+1R only count if the close is beyond them; `m15` = real M15 path (yfinance FX/metals, Binance crypto), 1h = 4 M15 bars from the fill; entry M15 bar treated like `cons`. "Touch-managed mid" = what live/stats do today (trade starts at first zone contact even if price never reaches the mid entry). "Mid limit fill" = a limit order at the mid must actually fill (within 24 H1 bars after the touch).

| Accounting | Model | Trades | WR | Avg R | PF | MaxDD R | IS avg R | OOS avg R |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B +1R live accounting (touch-managed mid) | legacy | 92 | 81.5% | 0.628 | 4.79 | 3.0 | 0.663 | 0.592 |
| B +1R live accounting (touch-managed mid) | cons | 92 | 72.8% | 0.374 | 2.90 | 4.9 | 0.396 | 0.352 |
| B +1R live accounting (touch-managed mid) | m15 | 92 | 73.9% | 0.502 | 3.63 | 3.5 | 0.480 | 0.524 |
| B +2R live accounting (touch-managed mid) | legacy | 92 | 75.0% | 0.992 | 6.27 | 4.9 | 1.112 | 0.873 |
| B +2R live accounting (touch-managed mid) | cons | 92 | 72.8% | 0.582 | 3.95 | 4.9 | 0.600 | 0.565 |
| B +2R live accounting (touch-managed mid) | m15 | 92 | 70.7% | 0.665 | 4.26 | 4.9 | 0.645 | 0.685 |
| B +1R realistic mid limit fill | legacy | 88 | 68.2% | 0.332 | 2.17 | 3.0 | 0.359 | 0.304 |
| B +1R realistic mid limit fill | cons | 88 | 56.8% | 0.027 | 1.09 | 5.3 | 0.010 | 0.045 |
| B +1R realistic mid limit fill | m15 | 88 | 55.7% | 0.104 | 1.31 | 6.2 | -0.008 | 0.217 |
| B +2R realistic mid limit fill | legacy | 88 | 59.1% | 0.333 | 2.08 | 5.0 | 0.365 | 0.301 |
| B +2R realistic mid limit fill | cons | 88 | 56.8% | 0.119 | 1.37 | 5.0 | 0.045 | 0.193 |
| B +2R realistic mid limit fill | m15 | 88 | 51.1% | 0.142 | 1.39 | 5.0 | 0.074 | 0.210 |

## 3. Main comparison (M15 path model, fill required, hold 1h unless stated)

Selection rule (fixed before looking at OOS): fill-required entries, TP = 2R, trades ≥ 40, ≥ 0.7 trades/weekday; rank by min(IS avg R, OOS avg R) × trades/weekday (= worst-half expectancy × volume). Grid: 5 realistic entries × 3 SL buffers × 4 holds × 2 star levels × 2 session filters × 3 management modes (+ TP 1R references) = 1152 configs × 3 models.

| Config | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Avg R net 0.02ATR | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| Realistic B +1R (mid limit fill, 1h, M15) | 88 | 3.30 | 55.7% | **0.104** [-0.07, 0.28] | 0.054 | 0.069 | 9.2 | 1.31 | 6.2 | 4 | -0.008 (44) | 0.217 (44) | no |
| Realistic plain B +2R (mid limit fill, 1h, M15) | 88 | 3.30 | 51.1% | **0.142** [-0.07, 0.35] | 0.092 | 0.107 | 12.5 | 1.39 | 5.0 | 5 | 0.074 (44) | 0.210 (44) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., 50% @+1R + BE, TP 2R | 78 | 2.94 | 53.8% | **0.316** [0.02, 0.60] | 0.266 | 0.251 | 24.6 | 1.70 | 5.0 | 5 | 0.472 (42) | 0.134 (36) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., BE@+1R, TP 2R | 78 | 2.94 | 41.0% | **0.325** [0.02, 0.63] | 0.275 | 0.260 | 25.4 | 1.72 | 5.0 | 5 | 0.494 (42) | 0.128 (36) | yes |
| 75% depth limit, SL distal+0.25ATR, hold 1h, ≥4★, all sess., BE@+1R, TP 2R | 78 | 2.94 | 37.2% | **0.113** [-0.13, 0.37] | 0.063 | 0.070 | 8.8 | 1.28 | 5.2 | 5 | 0.124 (42) | 0.101 (36) | yes |
| proximal limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., no mgmt, TP 2R | 92 | 3.47 | 51.1% | **0.087** [-0.06, 0.24] | 0.037 | 0.065 | 8.0 | 1.36 | 4.8 | 7 | 0.085 (46) | 0.088 (46) | yes |
| 75% depth limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., no mgmt, TP 2R | 78 | 2.94 | 46.2% | **0.348** [0.04, 0.68] | 0.298 | 0.269 | 27.1 | 1.66 | 8.0 | 8 | 0.566 (42) | 0.094 (36) | yes |
| proximal limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., no mgmt, TP 2R | 92 | 3.47 | 51.1% | **0.094** [-0.06, 0.26] | 0.044 | 0.071 | 8.6 | 1.37 | 5.2 | 7 | 0.075 (46) | 0.113 (46) | yes |
| 75% depth limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., 50% @+1R + BE, TP 2R | 78 | 2.94 | 50.0% | **0.292** [-0.01, 0.60] | 0.242 | 0.213 | 22.7 | 1.59 | 8.0 | 8 | 0.470 (42) | 0.083 (36) | yes |
| 75% depth limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., BE@+1R, TP 2R | 78 | 2.94 | 41.0% | **0.302** [-0.01, 0.61] | 0.252 | 0.224 | 23.6 | 1.61 | 8.0 | 8 | 0.490 (42) | 0.083 (36) | yes |

### ~1 trade/day variants (volume filters)

| Config | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Avg R net 0.02ATR | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, no mgmt, TP 1R | 41 | 1.44 | 56.1% | **0.120** [-0.16, 0.39] | 0.070 | 0.082 | 4.9 | 1.33 | 6.7 | 6 | -0.115 (21) | 0.367 (20) | no |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, no mgmt, TP 2R | 41 | 1.44 | 48.8% | **0.173** [-0.18, 0.53] | 0.123 | 0.135 | 7.1 | 1.42 | 7.1 | 6 | 0.107 (21) | 0.242 (20) | yes |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, BE@+1R, TP 2R | 41 | 1.44 | 46.3% | **0.205** [-0.13, 0.55] | 0.155 | 0.167 | 8.4 | 1.56 | 7.1 | 6 | 0.107 (21) | 0.308 (20) | yes |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, 50% @+1R + BE, TP 2R | 41 | 1.44 | 56.1% | **0.211** [-0.11, 0.53] | 0.161 | 0.174 | 8.7 | 1.57 | 6.9 | 6 | 0.044 (21) | 0.388 (20) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, Lon+NY, BE@+1R, TP 2R ⚠ n<40 | 38 | 1.36 | 39.5% | **0.279** [-0.16, 0.73] | 0.229 | 0.214 | 10.6 | 1.56 | 5.0 | 5 | 0.300 (20) | 0.256 (18) | yes |
| mid limit, SL distal+0.05ATR, hold 1h, ≥5★, all sess., no mgmt, TP 1R ⚠ n<40 | 23 | 0.88 | 39.1% | **-0.156** [-0.48, 0.17] | -0.206 | -0.192 | -3.6 | 0.64 | 3.6 | 4 | -0.229 (12) | -0.077 (11) | no |
| mid limit, SL distal+0.05ATR, hold 1h, ≥5★, all sess., no mgmt, TP 2R ⚠ n<40 | 23 | 0.88 | 39.1% | **-0.061** [-0.44, 0.36] | -0.111 | -0.097 | -1.4 | 0.86 | 3.1 | 4 | -0.182 (12) | 0.070 (11) | no |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., no mgmt, TP 1R + 1st fill/day ⚠ n<40 | 32 | 1.24 | 56.2% | **0.056** [-0.23, 0.36] | 0.006 | 0.018 | 1.8 | 1.15 | 4.1 | 3 | 0.154 (19) | -0.088 (13) | no |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, all sess., no mgmt, TP 2R + 1st fill/day ⚠ n<40 | 32 | 1.24 | 50.0% | **0.129** [-0.25, 0.50] | 0.079 | 0.091 | 4.1 | 1.32 | 5.0 | 3 | 0.358 (19) | -0.207 (13) | no |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., 50% @+1R + BE, TP 2R + 1st fill/day ⚠ n<40 | 31 | 1.18 | 48.4% | **0.147** [-0.27, 0.60] | 0.097 | 0.081 | 4.6 | 1.30 | 11.0 | 6 | 0.754 (18) | -0.692 (13) | no |

### Longer holds (info only — **needs holding longer than 1h**)

| Config | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Avg R net 0.02ATR | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 75% depth limit, SL distal+0.1ATR, hold 3h, ≥4★, all sess., BE@+1R, TP 2R ⏱ | 78 | 2.94 | 39.7% | **0.312** [0.01, 0.62] | 0.262 | 0.247 | 24.3 | 1.68 | 5.0 | 5 | 0.460 (42) | 0.139 (36) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 3h, ≥4★, all sess., 50% @+1R + BE, TP 2R ⏱ | 78 | 2.94 | 53.8% | **0.306** [0.02, 0.59] | 0.256 | 0.241 | 23.8 | 1.66 | 5.0 | 5 | 0.449 (42) | 0.139 (36) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 2h, ≥4★, all sess., BE@+1R, TP 2R ⏱ | 78 | 2.94 | 39.7% | **0.309** [0.00, 0.60] | 0.259 | 0.245 | 24.1 | 1.67 | 5.0 | 5 | 0.456 (42) | 0.139 (36) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 2h, ≥4★, all sess., 50% @+1R + BE, TP 2R ⏱ | 78 | 2.94 | 53.8% | **0.303** [0.01, 0.60] | 0.253 | 0.238 | 23.6 | 1.66 | 5.0 | 5 | 0.444 (42) | 0.139 (36) | yes |
| 75% depth limit, SL distal+0.1ATR, hold 4h, ≥4★, all sess., BE@+1R, TP 2R ⏱ | 78 | 2.94 | 38.5% | **0.295** [-0.01, 0.60] | 0.245 | 0.230 | 23.0 | 1.62 | 6.0 | 6 | 0.429 (42) | 0.139 (36) | yes |
| mid limit, SL distal+0.05ATR, hold 2h, ≥4★, all sess., no mgmt, TP 2R ⏱ | 88 | 3.30 | 48.9% | **0.157** [-0.10, 0.41] | 0.107 | 0.122 | 13.8 | 1.36 | 8.4 | 5 | -0.013 (44) | 0.327 (44) | no |
| mid limit, SL distal+0.05ATR, hold 3h, ≥4★, all sess., no mgmt, TP 2R ⏱ | 88 | 3.30 | 44.3% | **0.136** [-0.12, 0.41] | 0.086 | 0.101 | 12.0 | 1.27 | 8.9 | 5 | -0.075 (44) | 0.348 (44) | no |
| mid limit, SL distal+0.05ATR, hold 4h, ≥4★, all sess., no mgmt, TP 2R ⏱ | 88 | 3.30 | 46.6% | **0.187** [-0.09, 0.46] | 0.137 | 0.152 | 16.4 | 1.36 | 11.0 | 5 | -0.099 (44) | 0.473 (44) | no |

### Per group (M15 model)

| Config | METAUX n / WR / avg R | FOREX n / WR / avg R | CRYPTO n / WR / avg R |
|---|---|---|---|
| Realistic B +1R (mid limit fill, 1h, M15) | 16 / 56.2% / 0.004 | 42 / 52.4% / 0.104 | 30 / 60.0% / 0.159 |
| Realistic plain B +2R (mid limit fill, 1h, M15) | 16 / 50.0% / -0.060 | 42 / 50.0% / 0.175 | 30 / 53.3% / 0.204 |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., 50% @+1R + BE, TP 2R | 15 / 53.3% / 0.048 | 35 / 48.6% / 0.171 | 28 / 60.7% / 0.640 |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, all sess., BE@+1R, TP 2R | 15 / 33.3% / 0.010 | 35 / 34.3% / 0.171 | 28 / 53.6% / 0.686 |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, no mgmt, TP 2R | 11 / 54.5% / 0.043 | 22 / 40.9% / 0.050 | 8 / 62.5% / 0.689 |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, BE@+1R, TP 2R | 11 / 54.5% / 0.134 | 22 / 36.4% / 0.050 | 8 / 62.5% / 0.730 |
| mid limit, SL distal+0.05ATR, hold 1h, ≥4★, Lon+NY, 50% @+1R + BE, TP 2R | 11 / 63.6% / 0.190 | 22 / 45.5% / 0.081 | 8 / 75.0% / 0.600 |
| 75% depth limit, SL distal+0.1ATR, hold 1h, ≥4★, Lon+NY, BE@+1R, TP 2R | 9 / 33.3% / 0.179 | 20 / 30.0% / -0.050 | 9 / 66.7% / 1.111 |
| B +1R live accounting (touch-managed mid) [m15] | 16 / 100.0% / 0.971 | 43 / 72.1% / 0.473 | 33 / 63.6% / 0.310 |
| B +2R live accounting (touch-managed mid) [m15] | 16 / 93.8% / 1.397 | 43 / 69.8% / 0.588 | 33 / 60.6% / 0.410 |

### Neighbourhood of plain B +2R (vary one parameter, M15 model)

| Change | Trades | /weekday | Avg R | IS avg R | OOS avg R |
|---|---:|---:|---:|---:|---:|
| prox | 92 | 3.47 | 0.094 | 0.075 | 0.113 |
| d25 | 88 | 3.31 | 0.115 | 0.035 | 0.192 |
| d50 | 84 | 3.15 | 0.047 | -0.060 | 0.155 |
| d75 | 78 | 2.94 | 0.348 | 0.566 | 0.094 |
| sl0.1 | 88 | 3.30 | 0.133 | 0.073 | 0.192 |
| sl0.25 | 88 | 3.30 | 0.076 | 0.013 | 0.139 |
| h2 | 88 | 3.30 | 0.157 | -0.013 | 0.327 |
| h3 | 88 | 3.30 | 0.136 | -0.075 | 0.348 |
| h4 | 88 | 3.30 | 0.187 | -0.099 | 0.473 |
| s5 | 23 | 0.88 | -0.061 | -0.182 | 0.070 |
| lonny | 41 | 1.44 | 0.173 | 0.107 | 0.242 |
| be | 88 | 3.30 | 0.155 | 0.068 | 0.241 |
| partial | 88 | 3.30 | 0.152 | 0.053 | 0.252 |
| 1R | 88 | 3.30 | 0.104 | -0.008 | 0.217 |

## Caveats

- **Short sample**: H1 cache = 800 bars/symbol, so the analysis window is 2026-08-24 → 2026-10-05 (FX), with crypto only from 2026-09-05. That gives 78–92 trades per config, and each half covers about 3 weeks. The 95% CIs are about ±0.3R wide.
- **Multiple testing**: 1152 configs × 3 models. The selection rule (worst-half expectancy × volume) limits but does not remove optimism. The top grid configs are probably overstated.
- **Intrabar data**: FX/metals M15 comes from yfinance (the same feed as their H1, so levels are consistent; metals = futures GC/SI/HG/PA/PL). Crypto M15 is Binance spot 15m (fetched for this study, matches the H1 closes exactly). TON has no M15 after June, so its trades fall back to the H1 `cons` model (3 trades in plain B +2R). Within each M15 bar, SL is checked before TP. On the entry bar, TP/+1R only count on the close.
- **Fills**: a limit fills when price touches the level (no queue, no partial fills), within 24 H1 bars of the first zone contact. Alert latency and manual execution delay are not modelled; the zone is assumed known at the close of its detection bar.
- **Hold definition**: on M15, "1h" = 4 M15 bars from the fill. In the H1 models, hold 1 = the fill bar only (the old method's ≤1 bar).
- **Costs**: the headline numbers are gross. Net columns show −0.05R/trade and an alternative −0.02 H1-ATR/trade, which converts to more R for tighter stops (75% depth: median risk ≈0.32 ATR vs ≈0.63 ATR at mid). Crypto exchange fees could exceed both.
- Overlapping or concurrent positions are not limited, and there is no portfolio-level risk cap. Session filter = fill time in Paris (London 08:00–11:30, NY 14:30–17:30).
- Research only: no change to `fly.toml`, env, code paths used by production, or the deployed app. Not trading advice.


## Artifacts

- `data/backtest/summary_rr2_optim.json` — calibration, decomposition, headline/low-volume/longer-hold configs with by-group and IS/OOS
- `data/backtest/rr2_optim_grid.csv` — full grid (all configs × legacy/cons/m15)
- `data/backtest/rr2_optim_top.csv` — flat table of reported configs
- `data/backtest/trades_rr2_*.csv` — trade lists for the main configs
- `data/backtest/rr2_optim_meta.json` — windows, split dates, calibration
- Local caches (not committed, regenerable): `data/backtest/m15_binance/*.parquet` (`scripts/fetch_binance_m15.py`), `data/backtest/rr2_zones.pkl`, `data/backtest/rr2_trades_store.pkl`

Re-run: `.venv/bin/python scripts/fetch_binance_m15.py && .venv/bin/python scripts/rr2_optim_backtest.py && .venv/bin/python scripts/rr2_report.py`
