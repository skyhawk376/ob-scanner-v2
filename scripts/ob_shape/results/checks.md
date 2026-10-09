## hist (n=21894)
- OB candle before the broken pivot (OB is not part of the leg that broke structure): 2340 (10.7%)
- OB not at the leg extreme (leg_gap>0): 7170 (32.7%); leg extreme > 0.1 ATR beyond the zone (SL above/below the real swing): 3364 (15.4%)
- zone top above the broken level (bull) / bottom below (bear) (ob_to_bos_atr<0): 86
- BOS margin < 0.1 ATR (barely broke a pivot): 3258 (14.9%); BOS bars from OB median 2; broken pivot age median 6 bars
- born in chop (>5 of 10 prior bars overlap the zone): 13040 (59.6%)
- wick-dominated OB candle (body < 25% of range): 7188 (32.8%)
- weak displacement (max body OB+1..2 < 1 ATR): 7231 (33.0%); tiny FVG < 0.25 ATR: 8425 (38.5%)
- entry = OB open (zone <= 1 ATR) instead of the 50% mid: 15840 (72.3%)
- touch bar opened at/through the entry (gap fill): 274; prev close already beyond the proximal edge (gap across): 73
- NOT textbook (>=2 of T1-T8 fail): 13749 (62.8%); >=3 fails: 6895 (31.5%)
- 'Réaction +2R' status but a resting entry limit hit SL first: 6148/13198 (46.6%)

## prod (n=388)
- OB candle before the broken pivot (OB is not part of the leg that broke structure): 62 (16.0%)
- OB not at the leg extreme (leg_gap>0): 136 (35.1%); leg extreme > 0.1 ATR beyond the zone (SL above/below the real swing): 58 (14.9%)
- zone top above the broken level (bull) / bottom below (bear) (ob_to_bos_atr<0): 3
- BOS margin < 0.1 ATR (barely broke a pivot): 52 (13.4%); BOS bars from OB median 3; broken pivot age median 6 bars
- born in chop (>5 of 10 prior bars overlap the zone): 224 (57.7%)
- wick-dominated OB candle (body < 25% of range): 170 (43.8%)
- weak displacement (max body OB+1..2 < 1 ATR): 171 (44.1%); tiny FVG < 0.25 ATR: 173 (44.6%)
- entry = OB open (zone <= 1 ATR) instead of the 50% mid: 274 (70.6%)
- touch bar opened at/through the entry (gap fill): 11; prev close already beyond the proximal edge (gap across): 1
- NOT textbook (>=2 of T1-T8 fail): 273 (70.4%); >=3 fails: 160 (41.2%)
- 'Réaction +2R' status but a resting entry limit hit SL first: 95/269 (35.3%)

## prod_alerted (n=41)
- OB candle before the broken pivot (OB is not part of the leg that broke structure): 5 (12.2%)
- OB not at the leg extreme (leg_gap>0): 16 (39.0%); leg extreme > 0.1 ATR beyond the zone (SL above/below the real swing): 6 (14.6%)
- zone top above the broken level (bull) / bottom below (bear) (ob_to_bos_atr<0): 0
- BOS margin < 0.1 ATR (barely broke a pivot): 5 (12.2%); BOS bars from OB median 2; broken pivot age median 6 bars
- born in chop (>5 of 10 prior bars overlap the zone): 22 (53.7%)
- wick-dominated OB candle (body < 25% of range): 13 (31.7%)
- weak displacement (max body OB+1..2 < 1 ATR): 11 (26.8%); tiny FVG < 0.25 ATR: 13 (31.7%)
- entry = OB open (zone <= 1 ATR) instead of the 50% mid: 33 (80.5%)
- touch bar opened at/through the entry (gap fill): 3; prev close already beyond the proximal edge (gap across): 0
- NOT textbook (>=2 of T1-T8 fail): 22 (53.7%); >=3 fails: 11 (26.8%)
- 'Réaction +2R' status but a resting entry limit hit SL first: 6/20 (30.0%)

## Prod FOREX risk (entry→SL) in pips by TF (median / share < 3 pips)
| tf   |   count |   median |   <lambda_0> |
|:-----|--------:|---------:|-------------:|
| D    |      29 |    29    |         0    |
| H1   |      39 |    10.78 |         0    |
| H4   |      24 |    12.23 |         0.04 |
| M15  |      34 |     4.23 |         0.35 |
| M30  |      34 |     6.97 |         0.09 |
| M5   |      26 |     1.43 |         0.81 |
| W    |      20 |   130.25 |         0    |

## Telegram: same zone+event sent more than once: 1 cases
|                                                    |   0 |
|:---------------------------------------------------|----:|
| ('GBPAUD', 'H1', 'bull', 1.892, 1.894, 'reaction') |   3 |

## 'Invalidation / SL' messages that also say 'entrée mid pas encore atteinte': 16 of 18 SL messages
## Messages labelled '(milieu OB)': 62 — but for zones <= 1 ATR the engine uses the OB OPEN, not the mid (prod alerted zones with entry = open: 33/41)