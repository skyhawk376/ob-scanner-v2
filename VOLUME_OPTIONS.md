# Options de volume OB — ~1 trade/jour, hold max ~1h

Generated: **2026-10-05 21:41 CEST** (Europe/Paris)

## Méthode

- Repo: `/workspace/ob-scanner-v2-fly` — `scripts/volume_options_backtest.py`
- Soft reaction **OFF** (+1R / liquidité opposée) ; virgin OB ; `require_fvg=True`
- TF structure: **H1** ; hold max **1 barre H1** (exit sur la barre de touch, sinon `timeout_hold`)
- Cache: `/workspace/ob-scanner-v2/data/cache` (H1/H4/D/W uniquement — **aucun M15**)
- Fenêtre approx. touchées: 2026-06 → 2026-10 (span cache global plus large selon symbole)
- R: `echec` = **-1R** ; `reaction` = **+1R** ; max DD cumulatif en R
- **trades/jour (calendaire)** = closed / jours entre 1ʳᵉ et dernière touchée
- **trades/jour (jours ouvrés)** = closed / jours lun–ven sur la même plage (métrique cible ~1/jour)

## Matrice A–E

| | Setup | Signals | Closed | /jour cal. | /jour ouvrés | WR | Avg R | Sum R | Max DD | PF | Note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **A** | Baseline min_score=5, METAUX+FOREX+CRYPTO, H1, hold≤1 barre | 40 | 26 | 0.216 | 0.295 | 88.46% | 0.7692 | 20.0000 | 1.0000 | 7.67 | Référence qualité |
| **B** | min_score=4, mêmes groupes, H1, hold≤1 barre | 142 | 92 | 0.738 | 1.022 | 83.70% | 0.6739 | 62.0000 | 3.0000 | 5.13 | **Recommandé ~1/jour** |
| **C** | H1 structure / M15 entry | — | — | — | — | — | — | — | — | — | N/A — pas de cache M15. Proxy = A (touch→exit même barre H1) |
| **D** | min_score=5, M+F+C+NQ100, filtre London/NY sur NQ100 seul | 243 | 148 | 0.981 | 1.370 | 56.76% | 0.1351 | 20.0000 | 10.0000 | 1.31 | Volume OK, edge détruit (NQ≈0R) |
| **E** | Mix: score≥5 M+F+C + score≥4 METAUX | 54 | 36 | 0.289 | 0.400 | 91.67% | 0.8333 | 30.0000 | 1.0000 | 11.00 | Meilleure expectancy, volume insuffisant |

### C — M15

- Cache M15: **absent** (TFs dispo: H1, H4, D, W). Fetch M15 multi-symboles = coûteux / hors scope.
- Approximation demandée: **H1 touch → exit dans la même barre** ≡ configs A/B/D/E avec `max_hold_bars=1`.
- Donc C ≈ **A** (mêmes stats). Pas de gain de timing M15 mesurable ici.

### D — détail NQ100

- Filtre session London/NY appliqué **uniquement** au groupe NQ100 (session OB / touch).
- Résultat filtre: **203** signaux NQ retenus, tous label **NY** (0 London dans l’échantillon).
- NQ100 closed: **122**, WR **50%**, avg R **0.00**, sum R **0** → pure dilution.
- M+F+C dans D = identique à A (26 closed, +20R) ; le volume vient du NQ à expectancy nulle.

### Par groupe (hold ≤1 barre)

#### A — score≥5 M+F+C

| Group | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| METAUX | 8 | 5 | 100.00% | 1.0000 | 5.0000 |
| FOREX | 17 | 10 | 80.00% | 0.6000 | 6.0000 |
| CRYPTO | 15 | 11 | 90.91% | 0.8182 | 9.0000 |

#### B — score≥4 M+F+C

| Group | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| METAUX | 22 | 15 | 100.00% | 1.0000 | 15.0000 |
| FOREX | 71 | 42 | 80.95% | 0.6190 | 26.0000 |
| CRYPTO | 49 | 35 | 80.00% | 0.6000 | 21.0000 |

| Score (B) | Closed | WR | Avg R |
|---:|---:|---:|---:|
| 4 | 69 | 82.61% | 0.652 |
| 5 | 23 | 86.96% | 0.739 |

#### E — mix

| Group | Signals | Closed | WR | Avg R | Sum R |
|---|---:|---:|---:|---:|---:|
| METAUX (score≥4) | 22 | 15 | 100.00% | 1.0000 | 15.0000 |
| FOREX (score≥5) | 17 | 10 | 80.00% | 0.6000 | 6.0000 |
| CRYPTO (score≥5) | 15 | 11 | 90.91% | 0.8182 | 9.0000 |

## Référence hold non plafonné (A uncapped)

| Metric | Hold ≤1 barre (A) | Uncapped (lifecycle complet) |
|---|---:|---:|
| Closed | 26 | 28 |
| WR | 88.46% | 85.71% |
| Avg R | 0.7692 | 0.7143 |
| Max DD | 1.0 | 2.0 |

Presque toutes les sorties gagnantes sont déjà **same-bar** ; le cap 1h retire seulement 2 trades (timeout_hold).

## Recommandation (FR)

**Setup retenu pour ~1 trade/jour sans casser l’expectancy : B — `min_score=4`, groupes METAUX+FOREX+CRYPTO, H1, soft OFF (+1R), virgin OB, hold max 1 barre H1.**

- Volume: **~1.02 trade / jour ouvré** (0.74 / jour calendaire) — seule option A–E proche de la cible.
- Qualité: WR **83.7%**, avg R / expectancy **+0.67R**, sum **+62R**, max DD **3R**, PF **5.1**.
- vs A (score 5): expectancy un peu plus basse (0.77 → 0.67) mais volume ×3.5 ; les score-4 gardent un edge solide (+0.65R).
- **Éviter D** pour le volume: NQ100 (même filtré NY) apporte ~122 trades à **0R** d’expectancy et fait chuter l’ensemble à +0.14R / DD 10R.
- E est excellent en qualité (+0.83R) mais ~0.4/jour ouvré — trop rare vs objectif.
- C (M15): indisponible ; le proxy H1 same-bar est déjà intégré.

### Paramètres runtime suggérés

```
DEFAULT_SCAN_GROUPS=METAUX,FOREX,CRYPTO
MIN_SCORE=4
ENABLE_SOFT_REACTION=false
REACTION_R=1.0
# Hold discrétionnaire / monitor: viser sortie ≤1h (1 barre H1)
```

## Artifacts

- Ce rapport: `VOLUME_OPTIONS.md`
- Agrégat JSON: `data/backtest/summary_volume_options.json`
- Trades: `data/backtest/trades_vol_A_mfc_s5_hold1.csv`, `..._B_...`, `..._D_...`, `..._E_...`
- Script: `scripts/volume_options_backtest.py`

## Caveats

- Fenêtre H1 courte (~quelques mois) ; n=92 (B) reste un échantillon limité.
- Pas de spread / slippage / commission.
- Cap hold 1 barre = proxy du « max ~1h » ; pas un vrai M15 entry model.
- trades/jour ouvrés ignore le 24/7 crypto (sous-estime légèrement le dénominateur crypto).
- Pas un conseil de trading live.

