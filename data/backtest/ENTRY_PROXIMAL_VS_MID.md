# Entrée proximale vs mid — config B

Generated: **2026-10-05 23:48 CEST** (Europe/Paris)

Config B: `min_score=4`, METAUX+FOREX+CRYPTO (48 symboles H1), soft OFF (+1R), hold≤1 H1, OB vierge + FVG.

| Mode | Signaux | Fermés | W/L | WR | Avg R | Sum R | Max DD | PF | Trades/jour | Trades/jour ouvré |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mid (legacy) | 142 | 92 | 77/15 | 83.70% | 0.6739 | 62.0 | 3.0 | 5.13 | 0.738 | 1.033 |
| **proximal (live)** bull=haut OB / bear=bas OB | 142 | 61 | 46/15 | 75.41% | 0.5082 | 31.0 | 3.0 | 3.07 | 0.489 | 0.685 |

## Par groupe

| Groupe | Mode | Fermés | WR | Avg R | Sum R |
|---|---|---:|---:|---:|---:|
| CRYPTO | mid | 35 | 80.00% | 0.6000 | 21.0 |
| CRYPTO | proximal | 24 | 70.83% | 0.4167 | 10.0 |
| FOREX | mid | 42 | 80.95% | 0.6190 | 26.0 |
| FOREX | proximal | 28 | 71.43% | 0.4286 | 12.0 |
| METAUX | mid | 15 | 100.00% | 1.0000 | 15.0 |
| METAUX | proximal | 9 | 100.00% | 1.0000 | 9.0 |

- **proximal (code live)** : entrée bull=haut OB / bear=bas OB ; SL au-delà du bord distal (+0,05 ATR) ; R ≈ hauteur zone ; fill limite à l’entrée.
- **mid (legacy)** : entrée 50 % (ou open si zone < 1 ATR) ; gestion dès contact zone.
- Entrée bord distal (bull=bas / bear=haut) **retirée** du code (R ≈ buffer SL → WR 0 %).
- Pas de spread/commission/slippage.
## Contrôle robustesse — sans cap de durée (hold illimité)

| Mode | Fermés | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|
| mid | 97 | 82.47% | 0.6495 | 63.0 |
| proximal | 97 | 69.07% | 0.3814 | 37.0 |

(Sous hold≤1, 36 trades proximal sortent en `timeout_hold` vs 5 en mid : R plus large → +1R met plus de barres.)

## Décision deploy

Critère retenu : WR ≥ 60 % **et** avg R ≥ +0,30 R (hold≤1 et sans cap).
Proximal : 75,4 % / +0,51 R (hold≤1) et 69,1 % / +0,38 R (sans cap) → **acceptable → `fly deploy`**.
Reste inférieur au mid legacy (83,7 % / +0,67 R) : à surveiller en live.
