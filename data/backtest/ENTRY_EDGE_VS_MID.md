# Entrée edge vs mid — config B

Generated: **2026-10-05 23:42 CEST** (Europe/Paris)

Config B: `min_score=4`, METAUX+FOREX+CRYPTO, soft OFF (+1R), hold≤1 H1.

| Mode | Closed | WR | Avg R | Trades/jour | Trades/jour ouvré |
|---|---:|---:|---:|---:|---:|
| OLD mid (legacy) | 92 | 83.70% | 0.6739 | 0.738 | 1.033 |
| NEW edge bull=bas OB | 15 | 0.00% | -1.0000 | 0.120 | 0.168 |
| ALT proximal bull=haut OB | 61 | 75.41% | 0.5082 | 0.489 | 0.685 |

- **NEW edge (code live)**: entrée bull=bas OB / bear=haut OB ; SL au-delà bord opposé (distal +0,05 ATR) ; fill à l’entrée. Risk ≈ 0,05 ATR → wick de fill = SL même barre → WR 0 % sous hold≤1.
- **ALT proximal**: entrée bull=haut OB / bear=bas OB ; SL distal (R ≈ hauteur zone). Meilleur que distal mais sous le mid.
- **OLD mid**: entrée mid/open ; gestion dès contact zone.

**Décision deploy:** pas de `fly deploy` — régression stratégie (WR 0 % / avg R −1). Branche poussée pour revue.
