# Multi-timeframe momentum alignment filter on Filtre B (research only, no deploy)

Generated: **2026-10-06 10:16 CEST** (Europe/Paris). Branch `feat/always-on-fly`. Nothing deployed, Fly untouched.

Scripts: `scripts/momentum_filter_backtest.py` (bias + variants), `scripts/momentum_filter_report.py` (this file). Trade simulation is the **realistic simulator of `scripts/rr2_optim_backtest.py`** (imported unchanged): mid limit must actually fill (≤24 H1 bars after first touch), M15 price path (yfinance FX/metals, Binance crypto; H1-conservative fallback when no M15), every trade closed by TP / SL / **1h time stop**. Same causal zone detection (`rr2_zones.pkl`), same group windows, same IS/OOS split (each group window cut at its midpoint) and the same trades/weekday convention as `RR2_OPTIM.md`, so the baseline reproduces it exactly (88 trades, 55.7% / +0.104R at +1R; 51.1% / +0.142R at +2R).

## TL;DR

Realistic simulator, hold 1h, ≥4★, METAUX+FOREX+CRYPTO, entry mid (fill required), SL distal+0.05 ATR. Bias measured at the OB touch time on closed candles only. No costs except the "net" column.

| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| **B baseline +1R** | 88 | 3.30 | 55.7% | **+0.104** [-0.08, 0.29] | +0.054 | 9.2 | 1.31 | 6.2 | 4 | -0.008 (44) | +0.217 (44) | no | — |
| B + D1 [ema50] +1R | 48 | 1.88 | 62.5% | **+0.247** [0.02, 0.46] | +0.197 | 11.8 | 1.99 | 2.0 | 2 | +0.161 (22) | +0.320 (26) | yes | 40 / -0.067 / 0.050 |
| B + H4+D1 [ema50] +1R ⚠ n<40 | 35 | 1.35 | 65.7% | **+0.328** [0.09, 0.55] | +0.278 | 11.5 | 2.91 | 1.7 | 2 | +0.303 (17) | +0.350 (18) | yes | 53 / -0.043 / 0.026 |
| B + H1+H4+D1 [ema50] +1R ⚠ n<40 | 19 | 0.68 | 68.4% | **+0.466** [0.15, 0.75] | +0.416 | 8.9 | 4.80 | 1.0 | 2 | +0.437 (9) | +0.492 (10) | yes | 69 / +0.005 / 0.018 |
| B + ALL(M15+H1+H4+D1) [ema50] +1R ⚠ n<40 | 11 | 0.41 | 72.7% | **+0.461** [0.06, 0.80] | +0.411 | 5.1 | 5.56 | 1.0 | 1 | +0.214 (5) | +0.668 (6) | yes | 77 / +0.053 / 0.072 |
| B + ALL>=N-1 [ema2050] +1R ⚠ n<40 | 36 | 1.42 | 63.9% | **+0.338** [0.09, 0.57] | +0.288 | 12.2 | 2.86 | 2.0 | 2 | +0.303 (17) | +0.370 (19) | yes | 52 / -0.058 / 0.019 |
| **B baseline +2R** | 88 | 3.30 | 51.1% | **+0.142** [-0.08, 0.37] | +0.092 | 12.5 | 1.39 | 5.0 | 5 | +0.074 (44) | +0.210 (44) | yes | — |
| B + D1 [ema50] +2R | 48 | 1.88 | 56.2% | **+0.329** [0.05, 0.61] | +0.279 | 15.8 | 2.22 | 2.0 | 2 | +0.343 (22) | +0.317 (26) | yes | 40 / -0.083 / 0.037 |
| B + H4+D1 [ema50] +2R ⚠ n<40 | 35 | 1.35 | 60.0% | **+0.423** [0.11, 0.74] | +0.373 | 14.8 | 3.15 | 1.7 | 2 | +0.480 (17) | +0.370 (18) | yes | 53 / -0.044 / 0.020 |
| B + H1+H4+D1 [ema50] +2R ⚠ n<40 | 19 | 0.68 | 63.2% | **+0.619** [0.17, 1.05] | +0.569 | 11.8 | 5.06 | 1.0 | 2 | +0.760 (9) | +0.491 (10) | yes | 69 / +0.011 / 0.012 |
| B + ALL(M15+H1+H4+D1) [ema50] +2R ⚠ n<40 | 11 | 0.41 | 63.6% | **+0.545** [-0.02, 1.11] | +0.495 | 6.0 | 4.58 | 1.0 | 1 | +0.397 (5) | +0.668 (6) | yes | 77 / +0.084 / 0.087 |
| B + ALL>=N-1 [ema2050] +2R ⚠ n<40 | 36 | 1.42 | 55.6% | **+0.374** [0.07, 0.68] | +0.324 | 13.5 | 2.79 | 2.9 | 4 | +0.480 (17) | +0.278 (19) | yes | 52 / -0.019 / 0.042 |

Reading: `D1 [ema50]` = trade only if the last closed D1 close is on the OB side of the D1 EMA50 (bull OB: close > EMA50). `H4+D1` = both H4 and D1 agree. `ALL>=N-1` = at most one of M15/H1/H4/D1 disagrees. `Rejected` = trades the filter removes (their avg R) and a one-sided permutation p-value for selected − rejected.

### Findings

1. **The momentum effect is real in this sample but comes from the higher TFs (D1, then H4).** With the fixed selection rule (n ≥ 40, rank by worst-half avg R × trades/weekday, set before looking at results), the winner at both +1R and +2R is **B + D1 trend (close vs EMA50)**: 48 trades, 1.88/weekday, WR 62.5%, +0.247R at +1R (baseline +0.104R). Both halves positive, and the removed trades average -0.067R.
2. **Adding H4 (H4+D1, EMA-based) is the best "≈1 trade/day" variant**: 35 trades, 1.35/weekday, WR 65.7%, +0.328R (+1R) / +0.423R (+2R), PF 2.9–3.2, max DD 1.7R, both halves positive. It is slightly below the 40-trade bar, so it is flagged.
3. **Full alignment (Kasper "all TFs aligned") is too restrictive at 1h hold.** ALL(M15+H1+H4+D1) leaves 11 trades with EMA50 bias (+0.46R at +1R, 0.41/weekday). With strict market structure it leaves 0. H1+H4+D1 gives 19 trades (0.68/weekday, +0.47R / +0.62R). These look best per trade, but n is too small to trust and the volume drops well below 1/day.
4. **The market-structure bias (HH/HL vs LH/LL, fractal n=3) does not work as a filter here.** It is neutral ("range") on 25–55% of touches, so multi-TF variants collapse to <10 trades. D1 structure alone helps a little (+0.21R, n=32), and H4 structure gives nothing.
5. **Robust to the EMA length**: D1 close vs EMA20/30/50/100/200 all give +0.21 to +0.25R at +1R and +0.29 to +0.33R at +2R, with n 48–51 and both halves positive. H4+D1 with EMA100/200 keeps n ≥ 40 (43/47 trades, +0.30/+0.26R at +1R). The control (H4+D1 *against* the OB) is about 0R (+0.02R at +1R, +0.04R at +2R).
6. **+2R ≥ +1R for every EMA-based momentum variant** (D1: +0.329 vs +0.247; H4+D1: +0.423 vs +0.328), as in RR2. Most +2R trades still exit at the 1h time stop (D1: 31 time / 6 TP / 11 SL).
7. **Statistical caution.** About 21 filter variants × 2 TPs were tested, plus the EMA-length check. The best single permutation p-values are ~0.007–0.05, which do not survive a multiple-testing correction. The 95% bootstrap CIs of the filtered variants exclude 0 (D1: [+0.02, +0.46] at +1R), while the baseline's do not. Evidence is **suggestive, not conclusive**.

## Recommendation

- **Add a D1 trend gate, but first as a shadow tag, not a hard live filter.** Log the D1 bias (close vs D1 EMA50) and the H4 bias on every Filtre B alert and track the realistic outcome (actual mid fill, 1h time stop) for 4–6 more weeks. If the aligned/non-aligned split holds, switch it on.
- If you want to switch now, use the **D1-only gate** (≥40 trades, robust across EMA lengths, ≈1.9 trades/weekday). Use **H4+D1** if you prefer to be closer to **≈1 trade/day** (1.35/weekday, highest quality among variants with ≥35 trades). Keep TP +2R if RR2 is adopted, since the filter and +2R stack.
- **Do not adopt "all TFs aligned"** (M15+H1+H4+D1): it leaves ~0.4 trades/weekday and 11 trades in 6 weeks.
- Expect realistic numbers around 60–65% WR and +0.25 to +0.4R/trade before costs, **not** the 84% / +0.67R of the old method.

## Method

- **Bias time**: the open of the H1 touch bar (first zone contact). A TF bar counts only once fully closed (open + duration ≤ T; D1 bars dated d count from d+1 00:00 UTC). No lookahead.
- **TFs**: M15 = simulator M15 source (cache yfinance M15 for FX/metals, Binance M15 for crypto). H1 = H1 cache plus earlier history from cache M15 resampled. H4 = UTC 4h resample of that H1. D1 = yfinance daily (fetched once into `data/backtest/momentum_d1/`; GC=F/SI=F/PL=F/PA=F/HG=F for metals, `=X` FX, `-USD` crypto, SUI = SUI20947-USD). Missing: **M15 for TON** (Binance TON M15 ends June → skipped for TON). **D1 for TON** comes from an UTC resample of TON H1 (no correct Yahoo ticker). W1 not used (not requested; would need its own fetch). A missing/stale TF is skipped in the alignment test.
- **Bias definitions**: `struct` = last 2 confirmed fractal swing highs and lows (n=3, confirmed n bars later): HH+HL bull, LH+LL bear, else neutral. `ema50` = last closed close vs EMA50. `ema2050` = EMA20 vs EMA50. ≥50 closed bars are needed, otherwise neutral.
- **Alignment**: bull OB needs bullish bias (bear OB bearish); neutral counts as not aligned. `ALL>=N-1` = aligned on all available TFs but one. `no-opposite` = no TF against (neutral allowed; same as `all` for EMA defs).
- **Selection rule** (as in RR2, fixed in code): n ≥ 40, max of min(IS avg R, OOS avg R) × trades/weekday. Variants with n < 40 are flagged ⚠ and cannot win.
- Windows (UTC): METAUX 2026-08-20 09:00 → 2026-10-05 18:00 (33.1 weekdays); FOREX 2026-08-24 14:00 → 2026-10-05 18:00 (30.1 weekdays); CRYPTO 2026-09-05 19:00 → 2026-10-05 08:00 (21.1 weekdays). Trades/weekday = Σ_group trades / group weekdays.

## All variants — TP +1R

| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| B baseline | 88 | 3.30 | 55.7% | **+0.104** [-0.08, 0.29] | +0.054 | 9.2 | 1.31 | 6.2 | 4 | -0.008 (44) | +0.217 (44) | no | — |
| B + D1 [struct] ⚠ n<40 | 32 | 1.27 | 62.5% | **+0.210** [-0.08, 0.49] | +0.160 | 6.7 | 1.75 | 1.9 | 1 | +0.175 (15) | +0.241 (17) | yes | 56 / +0.044 / 0.183 |
| B + H4 [struct] ⚠ n<40 | 19 | 0.76 | 42.1% | **+0.110** [-0.25, 0.48] | +0.060 | 2.1 | 1.35 | 1.6 | 3 | +0.220 (8) | +0.030 (11) | yes | 69 / +0.103 / 0.478 |
| B + H4+D1 [struct] ⚠ n<40 | 9 | 0.40 | 55.6% | **+0.183** [-0.41, 0.78] | +0.133 | 1.7 | 1.49 | 1.3 | 2 | +0.600 (5) | -0.337 (4) | no | 79 / +0.095 / 0.401 |
| B + H1+H4+D1 [struct] ⚠ n<40 | 5 | 0.22 | 60.0% | **+0.330** [-0.47, 1.00] | +0.280 | 1.7 | 2.22 | 1.0 | 1 | +0.333 (3) | +0.325 (2) | yes | 83 / +0.091 / 0.299 |
| B + ALL(M15+H1+H4+D1) [struct] ⚠ n<40 | 0 | 0.00 | — | **—** [—, —] | — | 0.0 | — | — | 0 | — (0) | — (0) | no | 88 / +0.104 / — |
| B + ALL>=N-1 [struct] ⚠ n<40 | 8 | 0.34 | 50.0% | **+0.317** [-0.23, 0.75] | +0.267 | 2.5 | 2.74 | 1.0 | 2 | +0.225 (4) | +0.410 (4) | yes | 80 / +0.083 / 0.238 |
| B + H4+D1 no-opposite [struct] ⚠ n<40 | 39 | 1.48 | 56.4% | **+0.114** [-0.14, 0.36] | +0.064 | 4.5 | 1.38 | 3.5 | 2 | -0.005 (22) | +0.268 (17) | no | 49 / +0.096 / 0.453 |
| B + H4+D1 AGAINST (control) [struct] ⚠ n<40 | 6 | 0.24 | 50.0% | **+0.000** [-0.67, 0.67] | -0.050 | 0.0 | 1.00 | 1.0 | 1 | +0.000 (4) | +0.000 (2) | no | — |
| B + D1 [ema50] | 48 | 1.88 | 62.5% | **+0.247** [0.02, 0.46] | +0.197 | 11.8 | 1.99 | 2.0 | 2 | +0.161 (22) | +0.320 (26) | yes | 40 / -0.067 / 0.050 |
| B + H4 [ema50] | 46 | 1.77 | 56.5% | **+0.179** [-0.05, 0.40] | +0.129 | 8.2 | 1.67 | 3.0 | 3 | +0.122 (22) | +0.231 (24) | yes | 42 / +0.023 / 0.188 |
| B + H4+D1 [ema50] ⚠ n<40 | 35 | 1.35 | 65.7% | **+0.328** [0.09, 0.55] | +0.278 | 11.5 | 2.91 | 1.7 | 2 | +0.303 (17) | +0.350 (18) | yes | 53 / -0.043 / 0.026 |
| B + H1+H4+D1 [ema50] ⚠ n<40 | 19 | 0.68 | 68.4% | **+0.466** [0.15, 0.75] | +0.416 | 8.9 | 4.80 | 1.0 | 2 | +0.437 (9) | +0.492 (10) | yes | 69 / +0.005 / 0.018 |
| B + ALL(M15+H1+H4+D1) [ema50] ⚠ n<40 | 11 | 0.41 | 72.7% | **+0.461** [0.06, 0.80] | +0.411 | 5.1 | 5.56 | 1.0 | 1 | +0.214 (5) | +0.668 (6) | yes | 77 / +0.053 / 0.072 |
| B + ALL>=N-1 [ema50] ⚠ n<40 | 30 | 1.10 | 56.7% | **+0.199** [-0.09, 0.48] | +0.149 | 6.0 | 1.75 | 2.5 | 3 | +0.200 (16) | +0.199 (14) | yes | 58 / +0.055 / 0.225 |
| B + H4+D1 no-opposite [ema50] ⚠ n<40 | 35 | 1.35 | 65.7% | **+0.328** [0.09, 0.55] | +0.278 | 11.5 | 2.91 | 1.7 | 2 | +0.303 (17) | +0.350 (18) | yes | 53 / -0.043 / 0.026 |
| B + H4+D1 AGAINST (control) [ema50] ⚠ n<40 | 29 | 1.00 | 55.2% | **+0.020** [-0.32, 0.34] | -0.030 | 0.6 | 1.05 | 4.8 | 4 | -0.084 (17) | +0.167 (12) | no | — |
| B + D1 [ema2050] | 48 | 1.88 | 60.4% | **+0.204** [-0.02, 0.43] | +0.154 | 9.8 | 1.75 | 2.0 | 2 | +0.067 (22) | +0.320 (26) | yes | 40 / -0.015 / 0.118 |
| B + H4 [ema2050] | 50 | 1.94 | 58.0% | **+0.190** [-0.04, 0.42] | +0.140 | 9.5 | 1.68 | 2.8 | 2 | +0.142 (21) | +0.225 (29) | yes | 38 / -0.009 / 0.141 |
| B + H4+D1 [ema2050] ⚠ n<40 | 36 | 1.46 | 66.7% | **+0.344** [0.09, 0.58] | +0.294 | 12.4 | 2.79 | 1.7 | 2 | +0.435 (14) | +0.287 (22) | yes | 52 / -0.062 / 0.011 |
| B + H1+H4+D1 [ema2050] ⚠ n<40 | 25 | 1.02 | 68.0% | **+0.391** [0.10, 0.65] | +0.341 | 9.8 | 3.57 | 1.2 | 2 | +0.382 (11) | +0.398 (14) | yes | 63 / -0.009 / 0.020 |
| B + ALL(M15+H1+H4+D1) [ema2050] ⚠ n<40 | 3 | 0.09 | 66.7% | **+0.415** [-0.01, 1.00] | +0.365 | 1.2 | 124.26 | 0.0 | 1 | — (0) | +0.415 (3) | no | 85 / +0.093 / 0.234 |
| B + ALL>=N-1 [ema2050] ⚠ n<40 | 36 | 1.42 | 63.9% | **+0.338** [0.09, 0.57] | +0.288 | 12.2 | 2.86 | 2.0 | 2 | +0.303 (17) | +0.370 (19) | yes | 52 / -0.058 / 0.019 |
| B + H4+D1 no-opposite [ema2050] ⚠ n<40 | 36 | 1.46 | 66.7% | **+0.344** [0.09, 0.58] | +0.294 | 12.4 | 2.79 | 1.7 | 2 | +0.435 (14) | +0.287 (22) | yes | 52 / -0.062 / 0.011 |
| B + H4+D1 AGAINST (control) [ema2050] ⚠ n<40 | 26 | 0.93 | 57.7% | **+0.088** [-0.27, 0.44] | +0.038 | 2.3 | 1.23 | 3.0 | 3 | +0.086 (15) | +0.091 (11) | yes | — |

## All variants — TP +2R

| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| B baseline | 88 | 3.30 | 51.1% | **+0.142** [-0.08, 0.37] | +0.092 | 12.5 | 1.39 | 5.0 | 5 | +0.074 (44) | +0.210 (44) | yes | — |
| B + D1 [struct] ⚠ n<40 | 32 | 1.27 | 56.2% | **+0.303** [-0.05, 0.67] | +0.253 | 9.7 | 2.03 | 2.2 | 3 | +0.309 (15) | +0.298 (17) | yes | 56 / +0.050 / 0.131 |
| B + H4 [struct] ⚠ n<40 | 19 | 0.76 | 36.8% | **+0.087** [-0.30, 0.49] | +0.037 | 1.6 | 1.26 | 2.3 | 4 | +0.320 (8) | -0.083 (11) | no | 69 / +0.157 / 0.599 |
| B + H4+D1 [struct] ⚠ n<40 | 9 | 0.40 | 44.4% | **+0.125** [-0.56, 0.82] | +0.075 | 1.1 | 1.31 | 2.8 | 4 | +0.759 (5) | -0.668 (4) | no | 79 / +0.144 / 0.525 |
| B + H1+H4+D1 [struct] ⚠ n<40 | 5 | 0.22 | 40.0% | **+0.243** [-0.60, 1.31] | +0.193 | 1.2 | 1.73 | 1.0 | 2 | +0.629 (3) | -0.335 (2) | no | 83 / +0.136 / 0.400 |
| B + ALL(M15+H1+H4+D1) [struct] ⚠ n<40 | 0 | 0.00 | — | **—** [—, —] | — | 0.0 | — | — | 0 | — (0) | — (0) | no | 88 / +0.142 / — |
| B + ALL>=N-1 [struct] ⚠ n<40 | 8 | 0.34 | 37.5% | **+0.275** [-0.33, 0.93] | +0.225 | 2.2 | 2.23 | 1.0 | 2 | +0.446 (4) | +0.103 (4) | yes | 80 / +0.129 / 0.353 |
| B + H4+D1 no-opposite [struct] ⚠ n<40 | 39 | 1.48 | 53.8% | **+0.180** [-0.11, 0.48] | +0.130 | 7.0 | 1.58 | 3.3 | 2 | +0.086 (22) | +0.301 (17) | yes | 49 / +0.112 / 0.384 |
| B + H4+D1 AGAINST (control) [struct] ⚠ n<40 | 6 | 0.24 | 50.0% | **-0.058** [-0.79, 0.75] | -0.108 | -0.3 | 0.88 | 1.7 | 1 | -0.165 (4) | +0.156 (2) | no | — |
| B + D1 [ema50] | 48 | 1.88 | 56.2% | **+0.329** [0.05, 0.61] | +0.279 | 15.8 | 2.22 | 2.0 | 2 | +0.343 (22) | +0.317 (26) | yes | 40 / -0.083 / 0.037 |
| B + H4 [ema50] | 46 | 1.77 | 52.2% | **+0.228** [-0.04, 0.50] | +0.178 | 10.5 | 1.80 | 3.0 | 4 | +0.226 (22) | +0.230 (24) | yes | 42 / +0.048 / 0.205 |
| B + H4+D1 [ema50] ⚠ n<40 | 35 | 1.35 | 60.0% | **+0.423** [0.11, 0.74] | +0.373 | 14.8 | 3.15 | 1.7 | 2 | +0.480 (17) | +0.370 (18) | yes | 53 / -0.044 / 0.020 |
| B + H1+H4+D1 [ema50] ⚠ n<40 | 19 | 0.68 | 63.2% | **+0.619** [0.17, 1.05] | +0.569 | 11.8 | 5.06 | 1.0 | 2 | +0.760 (9) | +0.491 (10) | yes | 69 / +0.011 / 0.012 |
| B + ALL(M15+H1+H4+D1) [ema50] ⚠ n<40 | 11 | 0.41 | 63.6% | **+0.545** [-0.02, 1.11] | +0.495 | 6.0 | 4.58 | 1.0 | 1 | +0.397 (5) | +0.668 (6) | yes | 77 / +0.084 / 0.087 |
| B + ALL>=N-1 [ema50] ⚠ n<40 | 30 | 1.10 | 53.3% | **+0.279** [-0.07, 0.64] | +0.229 | 8.4 | 1.98 | 2.5 | 3 | +0.349 (16) | +0.198 (14) | yes | 58 / +0.071 / 0.186 |
| B + H4+D1 no-opposite [ema50] ⚠ n<40 | 35 | 1.35 | 60.0% | **+0.423** [0.11, 0.74] | +0.373 | 14.8 | 3.15 | 1.7 | 2 | +0.480 (17) | +0.370 (18) | yes | 53 / -0.044 / 0.020 |
| B + H4+D1 AGAINST (control) [ema50] ⚠ n<40 | 29 | 1.00 | 51.7% | **+0.035** [-0.35, 0.43] | -0.015 | 1.0 | 1.08 | 5.6 | 4 | -0.064 (17) | +0.176 (12) | no | — |
| B + D1 [ema2050] | 48 | 1.88 | 56.2% | **+0.288** [0.01, 0.57] | +0.238 | 13.8 | 2.03 | 2.0 | 2 | +0.203 (22) | +0.361 (26) | yes | 40 / -0.034 / 0.077 |
| B + H4 [ema2050] | 50 | 1.94 | 52.0% | **+0.261** [-0.01, 0.54] | +0.211 | 13.0 | 1.87 | 2.9 | 4 | +0.332 (21) | +0.209 (29) | yes | 38 / -0.014 / 0.109 |
| B + H4+D1 [ema2050] ⚠ n<40 | 36 | 1.46 | 61.1% | **+0.468** [0.14, 0.78] | +0.418 | 16.8 | 3.31 | 1.7 | 2 | +0.650 (14) | +0.352 (22) | yes | 52 / -0.084 / 0.007 |
| B + H1+H4+D1 [ema2050] ⚠ n<40 | 25 | 1.02 | 60.0% | **+0.470** [0.11, 0.84] | +0.420 | 11.7 | 3.81 | 1.3 | 2 | +0.545 (11) | +0.411 (14) | yes | 63 / +0.012 / 0.029 |
| B + ALL(M15+H1+H4+D1) [ema2050] ⚠ n<40 | 3 | 0.09 | 66.7% | **+0.604** [-0.01, 1.57] | +0.554 | 1.8 | 180.33 | 0.0 | 1 | — (0) | +0.604 (3) | no | 85 / +0.126 / 0.217 |
| B + ALL>=N-1 [ema2050] ⚠ n<40 | 36 | 1.42 | 55.6% | **+0.374** [0.07, 0.68] | +0.324 | 13.5 | 2.79 | 2.9 | 4 | +0.480 (17) | +0.278 (19) | yes | 52 / -0.019 / 0.042 |
| B + H4+D1 no-opposite [ema2050] ⚠ n<40 | 36 | 1.46 | 61.1% | **+0.468** [0.14, 0.78] | +0.418 | 16.8 | 3.31 | 1.7 | 2 | +0.650 (14) | +0.352 (22) | yes | 52 / -0.084 / 0.007 |
| B + H4+D1 AGAINST (control) [ema2050] ⚠ n<40 | 26 | 0.93 | 53.8% | **+0.094** [-0.31, 0.52] | +0.044 | 2.4 | 1.22 | 3.9 | 3 | +0.060 (15) | +0.141 (11) | yes | — |

## Per group (WR / avg R, n)

| Variant | TP | METAUX | FOREX | CRYPTO |
|---|---|---|---|---|
| B baseline | +1R | 16 / 56.2% / +0.004 | 42 / 52.4% / +0.104 | 30 / 60.0% / +0.159 |
| B + D1 [ema50] | +1R | 4 / 75.0% / +0.314 | 23 / 60.9% / +0.258 | 21 / 61.9% / +0.221 |
| B + H4+D1 [ema50] | +1R | 4 / 75.0% / +0.314 | 17 / 64.7% / +0.386 | 14 / 64.3% / +0.260 |
| B + H1+H4+D1 [ema50] | +1R | 3 / 66.7% / +0.085 | 12 / 66.7% / +0.495 | 4 / 75.0% / +0.665 |
| B + H4+D1 against [ema50] | +1R | 12 / 50.0% / -0.100 | 12 / 50.0% / +0.008 | 5 / 80.0% / +0.333 |
| B baseline | +2R | 16 / 50.0% / -0.060 | 42 / 50.0% / +0.175 | 30 / 53.3% / +0.204 |
| B + D1 [ema50] | +2R | 4 / 75.0% / +0.507 | 23 / 56.5% / +0.353 | 21 / 52.4% / +0.269 |
| B + H4+D1 [ema50] | +2R | 4 / 75.0% / +0.507 | 17 / 58.8% / +0.509 | 14 / 57.1% / +0.295 |
| B + H1+H4+D1 [ema50] | +2R | 3 / 66.7% / +0.274 | 12 / 58.3% / +0.613 | 4 / 75.0% / +0.894 |
| B + H4+D1 against [ema50] | +2R | 12 / 41.7% / -0.250 | 12 / 50.0% / +0.106 | 5 / 80.0% / +0.548 |

Most METAUX OBs in this window ran against the H4/D1 trend: 12 of 16 trades are *against* H4+D1. The filter therefore keeps only 4 metal trades, and the gain comes from FOREX and CRYPTO.

## Robustness — EMA length (close vs EMA_span)

| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| B + D1 close>EMA20 +1R | 48 | 1.88 | 60.4% | **+0.220** [-0.01, 0.44] | +0.170 | 10.6 | 1.82 | 2.4 | 2 | +0.190 (20) | +0.242 (28) | yes | 40 / -0.035 / 0.084 |
| B + H4+D1 close>EMA20 +1R ⚠ n<40 | 30 | 1.13 | 56.7% | **+0.143** [-0.14, 0.42] | +0.093 | 4.3 | 1.51 | 2.5 | 3 | +0.127 (15) | +0.159 (15) | yes | 58 / +0.084 / 0.368 |
| B + D1 close>EMA20 +2R | 48 | 1.88 | 54.2% | **+0.313** [0.02, 0.60] | +0.263 | 15.0 | 2.09 | 2.9 | 4 | +0.390 (20) | +0.259 (28) | yes | 40 / -0.064 / 0.045 |
| B + H4+D1 close>EMA20 +2R ⚠ n<40 | 30 | 1.13 | 53.3% | **+0.243** [-0.12, 0.61] | +0.193 | 7.3 | 1.81 | 2.5 | 3 | +0.321 (15) | +0.164 (15) | yes | 58 / +0.090 / 0.236 |
| B + D1 close>EMA30 +1R | 48 | 1.88 | 60.4% | **+0.220** [-0.01, 0.44] | +0.170 | 10.6 | 1.82 | 2.4 | 2 | +0.190 (20) | +0.242 (28) | yes | 40 / -0.035 / 0.084 |
| B + H4+D1 close>EMA30 +1R ⚠ n<40 | 35 | 1.35 | 57.1% | **+0.195** [-0.06, 0.45] | +0.145 | 6.8 | 1.76 | 2.0 | 2 | +0.211 (18) | +0.178 (17) | yes | 53 / +0.044 / 0.212 |
| B + D1 close>EMA30 +2R | 48 | 1.88 | 54.2% | **+0.313** [0.02, 0.60] | +0.263 | 15.0 | 2.09 | 2.9 | 4 | +0.390 (20) | +0.259 (28) | yes | 40 / -0.064 / 0.045 |
| B + H4+D1 close>EMA30 +2R ⚠ n<40 | 35 | 1.35 | 51.4% | **+0.245** [-0.06, 0.57] | +0.195 | 8.6 | 1.88 | 2.9 | 4 | +0.378 (18) | +0.105 (17) | yes | 53 / +0.074 / 0.225 |
| B + D1 close>EMA50 +1R | 48 | 1.88 | 62.5% | **+0.247** [0.02, 0.46] | +0.197 | 11.8 | 1.99 | 2.0 | 2 | +0.161 (22) | +0.320 (26) | yes | 40 / -0.067 / 0.050 |
| B + H4+D1 close>EMA50 +1R ⚠ n<40 | 35 | 1.35 | 65.7% | **+0.328** [0.09, 0.55] | +0.278 | 11.5 | 2.91 | 1.7 | 2 | +0.303 (17) | +0.350 (18) | yes | 53 / -0.043 / 0.026 |
| B + D1 close>EMA50 +2R | 48 | 1.88 | 56.2% | **+0.329** [0.05, 0.61] | +0.279 | 15.8 | 2.22 | 2.0 | 2 | +0.343 (22) | +0.317 (26) | yes | 40 / -0.083 / 0.037 |
| B + H4+D1 close>EMA50 +2R ⚠ n<40 | 35 | 1.35 | 60.0% | **+0.423** [0.11, 0.74] | +0.373 | 14.8 | 3.15 | 1.7 | 2 | +0.480 (17) | +0.370 (18) | yes | 53 / -0.044 / 0.020 |
| B + D1 close>EMA100 +1R | 50 | 1.97 | 60.0% | **+0.206** [-0.02, 0.43] | +0.156 | 10.3 | 1.76 | 2.0 | 2 | +0.161 (22) | +0.242 (28) | yes | 38 / -0.030 / 0.103 |
| B + H4+D1 close>EMA100 +1R | 43 | 1.72 | 65.1% | **+0.303** [0.08, 0.52] | +0.253 | 13.0 | 2.38 | 2.0 | 2 | +0.368 (17) | +0.260 (26) | yes | 45 / -0.085 / 0.016 |
| B + D1 close>EMA100 +2R | 50 | 1.97 | 54.0% | **+0.285** [0.01, 0.57] | +0.235 | 14.3 | 1.98 | 2.9 | 4 | +0.343 (22) | +0.240 (28) | yes | 38 / -0.046 / 0.072 |
| B + H4+D1 close>EMA100 +2R | 43 | 1.72 | 58.1% | **+0.405** [0.11, 0.70] | +0.355 | 17.4 | 2.68 | 2.9 | 4 | +0.604 (17) | +0.275 (26) | yes | 45 / -0.110 / 0.007 |
| B + D1 close>EMA200 +1R | 51 | 2.01 | 62.7% | **+0.243** [0.03, 0.45] | +0.193 | 12.4 | 1.99 | 2.0 | 2 | +0.211 (22) | +0.268 (29) | yes | 37 / -0.087 / 0.042 |
| B + H4+D1 close>EMA200 +1R | 47 | 1.85 | 63.8% | **+0.264** [0.04, 0.49] | +0.214 | 12.4 | 2.08 | 2.0 | 2 | +0.232 (20) | +0.288 (27) | yes | 41 / -0.079 / 0.032 |
| B + D1 close>EMA200 +2R | 51 | 2.01 | 56.9% | **+0.322** [0.06, 0.60] | +0.272 | 16.4 | 2.22 | 2.9 | 4 | +0.393 (22) | +0.269 (29) | yes | 37 / -0.107 / 0.028 |
| B + H4+D1 close>EMA200 +2R | 47 | 1.85 | 57.4% | **+0.359** [0.07, 0.65] | +0.309 | 16.9 | 2.36 | 2.9 | 4 | +0.432 (20) | +0.305 (27) | yes | 41 / -0.107 / 0.019 |

## Sensitivity — bias at fill time instead of touch time

| Variant | Trades | /weekday | WR | Avg R [95% CI] | Avg R net 0.05R | Sum R | PF | MaxDD R | Max L streak | IS avg R (n) | OOS avg R (n) | Both halves > 0 | Rejected n / avg R / perm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| B + D1 @fill [ema50] +1R | 48 | 1.88 | 62.5% | **+0.247** [0.02, 0.46] | +0.197 | 11.8 | 1.99 | 2.0 | 2 | +0.161 (22) | +0.320 (26) | yes | — |
| B + D1 @fill [ema50] +2R | 48 | 1.88 | 56.2% | **+0.329** [0.05, 0.61] | +0.279 | 15.8 | 2.22 | 2.0 | 2 | +0.343 (22) | +0.317 (26) | yes | — |

## Old method (reference only — inflated, do not use for decisions)

Old method = `simulate_lifecycle`, mid managed from first contact, H1 OHLC, unresolved trades **dropped** (see RR2_OPTIM.md §1).

| Variant | TP | Closed | WR | Avg R | PF | Trades/weekday (per-group windows) |
|---|---|---:|---:|---:|---:|---:|
| B baseline (old method) | +1R | 92 | 83.7% | +0.674 | 5.13 | 3.28 |
| B + D1 [ema50] (old method) | +1R | 50 | 88.0% | +0.760 | 7.33 | 1.77 |
| B baseline (old method) | +2R | 64 | 76.6% | +1.297 | 6.53 | 2.26 |
| B + D1 [ema50] (old method) | +2R | 31 | 80.6% | +1.419 | 8.33 | 1.10 |

## Caveats

- **Sample size**: ~6 weeks (crypto ~4) of H1, 88 baseline trades. Filtered variants have 11–51 trades. One market regime. Many variants were tested (see Findings 7).
- **No costs/slippage/spread** in the main metrics. The "net 0.05R" column subtracts a flat 0.05R/trade (RR2 convention).
- D1 for metals comes from **futures** (GC=F etc.), while trades use spot/OANDA-like H1. The trend sign is the same in practice, but the levels differ.
- H4 is a UTC-aligned resample (00/04/08… UTC). Broker H4 candles (e.g. NY-close aligned) can differ slightly.
- TON: no M15 path after June (simulator falls back to H1-conservative) and D1 is resampled from H1.
- The realistic simulator still assumes a resting limit at the mid for 24 H1 bars after the touch, and conservative fill-bar handling.
- Research only: nothing changed in the scanner, API, Telegram or Fly.

