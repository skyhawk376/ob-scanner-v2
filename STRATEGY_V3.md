# OB Scanner v3 « Kasper » — règles exactes

Moteur : `backend/app/v3/` (`params.py` = tous les paramètres). Même code pour le live et le backtest
(`scripts/v3/backtest.py`). Source des règles : `/workspace/kasper/KASPER_TRADING.md` + plan validé par Oscar.

## 1. Order Block
- **OB** = dernière bougie de couleur opposée avant un mouvement violent : bull = bougie baissière (close < open) suivie d'une bougie haussière ; bear = miroir.
- **Zone** = range complet de la bougie OB, **mèches incluses** (low → high).
- **Mouvement violent** : dans les 3 bougies après l'OB (`IMPULSE_BARS=3`), l'extrême dépasse le bord proximal de l'OB d'au moins **1,0 ATR(14)** (`IMPULSE_ATR`).
- **FVG obligatoire** (prérequis, pas une étoile) : dans l'impulsion, 3 bougies (k-1, k, k+1) avec k-1 ≥ OB et k+1 ≤ OB+3 telles que `low[k+1] > high[k-1]` (bull) / `high[k+1] < low[k-1]` (bear). La 3ᵉ bougie du FVG doit être **clôturée** (une zone stockée ne change jamais). La zone est « armée » à partir de la bougie k+2.
- **Invalidation** : clôture d'une bougie de la TF de la zone au-delà du bord distal (sous le low pour un achat, au-dessus du high pour une vente).
- **Expiration** : 300 bougies de la TF de la zone après l'OB (`MAX_AGE_BARS`) sans trade.

## 2. Étoiles (≥ 4★ sur 5 pour être affichée / alertée)
| ★ | Règle objective |
|---|---|
| Tendance | Structure de Dow avec pivots fractals 3/3 confirmés (p+3 ≤ bougie OB) : 2 derniers swing highs **et** 2 derniers swing lows. Bull = HH + HL, bear = LH + LL, sinon range → pas d'étoile. Doit être dans le sens de la zone. |
| Liquidité prise | Un pivot (low pour bull / high pour bear) confirmé dans les 30 bougies avant l'OB (`LIQ_LOOKBACK`), jamais pris jusqu'à la fenêtre de sweep, est percé par une mèche des bougies [OB-2 … OB] (`SWEEP_WIN=3`). Les equal lows/highs sont des pivots → inclus. |
| OB jamais touché | Aucune touche depuis l'armement. **Étoile, plus un prérequis** : une zone déjà touchée (non invalidée) peut se requalifier au 2ᵉ toucher si elle a les 4 autres étoiles. |
| Fibo 0,5 | Jambe = bord distal de l'OB → extrême de l'impulsion atteint avant l'évaluation (le toucher). Bull : bord proximal (high) ≤ niveau 0,5 (toute la zone en discount). Bear : bord proximal (low) ≥ 0,5 (premium). |
| Session | Bougie OB **ouverte** du lundi au vendredi entre **08:00 et 21:00 Europe/Paris** (zoneinfo, heure d'été gérée). H4 inclus ; D et W : jamais (une bougie couvre toutes les sessions). |

Le score affiché pour une zone active = étoiles évaluées maintenant (vierge = oui) ; au toucher, le score est figé avec l'état réel (vierge, Fibo au moment du toucher).

## 3. Déclencheur d'entrée (TF inférieure)
- Après le toucher (bord proximal atteint), on attend une **bougie de retournement clôturée** sur la TF inférieure : M5→M1, M15→M5, M30→M15, H1→M15, H4→H1, D→H4, W→D.
- **Fenêtre** : 3 bougies de la TF de la zone à partir de la bougie du toucher (`WINDOW_BARS=3`), et avant l'invalidation.
- **Englobante** (bull) : bougie précédente baissière, bougie haussière dont le corps englobe le corps précédent (`open ≤ close_prev` et `close ≥ open_prev`). Miroir en bear.
- **Marteau / pin bar** (bull) : mèche basse ≥ 2× corps (corps plancher = 5 % du range) et clôture dans le tiers haut. Bear : « étoile filante », miroir.
- La bougie doit atteindre la zone (low ≤ proximal + 0,10 ATR) et clôturer **dans/au-dessus** de la zone, pas au-delà du bord distal.
- Pas de bougie dans la fenêtre → zone « touchée, en attente » ; un nouveau toucher n'est possible qu'après que le prix est **ressorti** de la zone (max 2 messages « Zone touchée » par zone).
- **Entrée** = clôture de la bougie de retournement (au marché). **SL** = bord distal ∓ 0,05 ATR. **TP** = +2R depuis l'entrée réelle. Un seul trade par zone.

## 4. Gestion
- À **+1R** : message « Passe ton SL au point d'entrée » et le SL du trade suivi passe à l'entrée (break-even).
- **Pas de time stop.** Sorties : TP (+2R), SL (−1R), BE (0R brut, négatif net de frais).
- Même bougie SL + TP/1R → SL d'abord (conservateur). Les stops se déclenchent à mid ± ½ spread.

## 5. Coûts (stats et backtest, `app/v3/costs.py`)
Repris de `scripts/strategy_research/common.py` et étendu : spread payé une fois, commission aller-retour, slippage à l'entrée (marché) et à la sortie stop (SL/BE). FX : 0,2–1,0 pip selon la paire (croisées 1,2) + 0,6 pip de commission + 0,2 pip de slippage ; XAU 0,25 + 0,07 + 0,10 ; XAG 0,025 + 0,004 + 0,01 ; BTC/ETH/SOL 1 bp + 5 bp + 2 bp ; alts 3 bp + 5 bp + 3 bp ; NAS100 1,5 pt + 1 pt.

## 6. Alertes Telegram (même bot, même chat)
1. 🟡 **Zone touchée** (préparation) : étoiles, TF, symbole, zone, TF inférieure, heure limite, SL prévu.
2. 🟢 **ENTRÉE** : entrée / SL / TP, type de bougie et TF inférieure.
3. 🔵 **+1R → Passe ton SL au point d'entrée**.
4. ✅ / ❌ / ⚪ **Résultat** TP / SL / BE en R net.

Garde-fous : une seule fois par (zone, événement) (claim SQLite `v3_notify` avant l'envoi) ; **go-live** par TF (1er passage v3 silencieux, seuls les événements postérieurs sont envoyés) ; fraîcheur : toucher/entrée ignorés s'ils ont plus de max(30 min, 2 bougies de TF inférieure) ; +1R et résultat **seulement si l'ENTRÉE a été envoyée** ; `ALERT_TFS` (défaut : les 7 TF) ; au plus 8 « Zone touchée » par cycle ; ~1 msg/s. Plus de ligne de tendance H4/D1. Récap unique à 07:45 (zones actives + stats live).

## 7. Cycle de vie (live)
Chaque TF à sa cadence (`TF_SCHEDULE`) : fetch → détection sur le cache → simulation de chaque zone (sans état, rejouée à chaque cycle) → SQLite `v3_zones` → alertes. Une zone vivante stockée est **toujours** re-simulée, même si elle ne sort plus de la détection (fix « vanished zone »). À chaque tick, toutes les zones touchées / en position des autres TF sont aussi suivies sur leur TF inférieure (rafraîchie à la demande : M1 Binance pour la crypto, Yahoo 1m sinon).

## 8. Univers
METAUX (5), FOREX (28), CRYPTO (15) et **NQ100 = l'indice NAS100 (Yahoo `NQ=F`, futures ~23 h/24, 1m dispo)**. `V3_NQ100_STOCKS=true` ajoute les ~60 actions (cycle plus long). TF : M5, M15, M30, H1, H4, D, W.

## 9. Backtest de contrôle (pas une optimisation)
`/tmp/obv/bin/python scripts/v3/backtest.py --start 2025-10-01 --end 2026-09-30` : M1 historique de XAU, XAG, 7 paires FX, BTC/ETH/SOL et NAS100 (15 symboles), 260 jours ouvrés. Résultats : `data/backtest/v3_sanity/summary.json`, copiés dans `backend/app/v3/backtest_summary.json` (affichés dans l'onglet Réaction).

| | Trades | Trades/jour | WR (TP) | R moyen brut | R moyen net |
|---|---|---|---|---|---|
| Tous | 18 925 | 72,8 | 23,7 % | −0,04 | **−0,50** |
| M5 | 12 807 | 49,3 | 23,1 % | −0,06 | −0,63 |
| M15 | 3 393 | 13,1 | 24,5 % | −0,02 | −0,29 |
| M30 | 1 554 | 6,0 | 25,6 % | +0,02 | −0,15 |
| H1 | 987 | 3,8 | 24,2 % | −0,02 | −0,16 |
| H4 | 172 | 0,66 | 23,8 % | −0,03 | −0,09 |
| D | 11 | 0,04 | 27 % | +0,18 | +0,09 |

Lecture : avant frais, l'avantage est nul (≈ 0R). Après frais, c'est négatif, surtout sur M5 et M15 où le SL est petit. Volume : ≈ 120 « Zone touchée » et 73 entrées par jour ouvré pour 15 symboles. Le live suit 49 symboles, donc **environ 3 fois plus**. Pour réduire : `ALERT_TFS=M30,H1,H4,D,W` (variable d'environnement Fly), sans changer le code.

## 10. Rollback
Avant le déploiement v3, la prod était en **v19**, image `registry.fly.io/ob-scanner-v2:deployment-01M4D1J4D40FQ67V01X6MPQDBX`. Le code correspondant est taggé `v2-final`.
```
export PATH=$HOME/.fly/bin:$PATH
flyctl deploy -a ob-scanner-v2 --image registry.fly.io/ob-scanner-v2:deployment-01M4D1J4D40FQ67V01X6MPQDBX
```
Les tables v2 (`zones`, `notify_log`) restent intactes dans `/data/results/zones.sqlite`. Les tables v3 sont préfixées `v3_`, donc un rollback n'a rien à migrer.
