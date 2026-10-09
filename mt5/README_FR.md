# OB Kasper v3 — Expert Advisor MetaTrader 5

`OB_Kasper_v3.mq5` reprend **exactement** les règles du scanner v3 « Kasper »
(`backend/app/v3/` + `STRATEGY_V3.md`) pour les backtester dans le testeur de stratégie MT5,
et éventuellement les trader en démo. La prod (Fly) n'est pas touchée.

## 1. Installation
1. MT5 → *Fichier → Ouvrir le dossier des données* → `MQL5\Experts\` : copier `OB_Kasper_v3.mq5`.
2. Ouvrir le fichier dans MetaEditor (F4 depuis MT5) puis **compiler (F7)**. Il faut 0 erreur. Les avertissements sont sans gravité.
3. Dans le Navigateur MT5, l'EA apparaît sous *Experts* (clic droit → Actualiser si besoin).
4. En démo : glisser l'EA sur un graphique du symbole, cocher « Autoriser le trading algorithmique ».
   La TF du graphique n'a pas d'importance : c'est `InpZoneTF` qui décide.

## 2. Règles implémentées (rappel)
- **OB** : dernière bougie de couleur opposée suivie d'une bougie dans le sens du mouvement. Zone = mèches comprises.
- **Impulsion** : dans les 3 bougies suivantes, l'extrême dépasse le bord proximal d'au moins 1,0 ATR(14) (Wilder).
- **FVG obligatoire** : `low[k+1] > high[k-1]` (bull) dans l'impulsion. La zone est **armée** à k+2.
- **Invalidation** : une clôture de la TF de zone au-delà du bord distal. **Expiration** : 300 bougies après l'OB.
- **Étoiles (≥ 4/5)** : Tendance (Dow, pivots 3/3), Liquidité prise (30 bougies, sweep par OB-2..OB),
  Jamais touché, Fibo 0,5 (jambe distal → extrême de l'impulsion avant le toucher), Session (lun–ven
  08:00–21:00 Paris, heure d'été gérée, jamais en D/W).
- **Déclencheur** sur la TF inférieure (M5→M1, M15→M5, M30→M15, H1→M15, H4→H1, D→H4, W→D),
  bougie **clôturée** : englobante ou marteau / étoile filante (mèche ≥ 2× corps, clôture dans le tiers extérieur).
  Elle doit atteindre la zone à 0,1 ATR près et clôturer dedans. Fenêtre : 3 bougies de la TF de zone, et elle s'arrête à l'invalidation.
  Un nouveau toucher n'est possible qu'après que le prix est ressorti de la zone.
- **Trade** : entrée au marché au tick suivant la clôture du déclencheur. SL = bord distal ∓ 0,05 ATR. TP = +2R calculé depuis le prix réel.
  À +1R, le SL passe à l'entrée (+ décalage optionnel). Pas de time stop. Un seul trade par zone.

Note « max 2 touches » : dans `sim.py`, la limite de 2 ne s'applique qu'aux **messages** « Zone touchée ».
Un 3ᵉ toucher peut encore déclencher une entrée (il faut alors les 4 autres étoiles, car la zone n'est plus vierge).
L'EA fait pareil par défaut (`InpMaxTouches = 0`). Mettre `2` pour limiter réellement les entrées aux 2 premiers touchers.

## 3. Paramètres principaux
| Input | Défaut | Rôle |
|---|---|---|
| InpZoneTF | H1 | TF de la zone (M5, M15, M30, H1, H4, D1, W1) |
| InpMinStars | 4 | étoiles minimum. Une étoile désactivée (`InpStar*` = false) ne compte jamais : baisser MinStars en conséquence |
| InpAtrPeriod / InpImpulseAtr / InpFvgRequired | 14 / 1.0 / true | détection |
| InpTrigEngulf / InpTrigPin / InpWindowBars | true / true / 3 | déclencheur |
| InpTpR / InpBeAtR / InpBeOffsetPts / InpBeAddSpread | 2.0 / 1.0 / 0 / false | gestion (BeAtR = 0 désactive le BE) |
| InpRiskPct / InpFixedLots | 0.5 % / 0.01 | taille (risque % du solde ; si le lot calculé < lot minimum, le trade est **refusé** et journalisé « skipped ») |
| InpMaxTrades | 3 | positions simultanées max (symbole + magic) |
| InpMaxSpreadPts | 0 (off) | filtre de spread |
| InpSrvMode / InpSrvOffsetHours | Auto / 2 | heure serveur (voir §6) |
| InpHistoryBars / InpWarmupBars | 1000 / 300 | historique pour ATR/pivots ; bougies rejouées au démarrage (sans trader) |
| InpDraw | true | zones + étiquettes (étoiles, TLVFS) en mode visuel / live |

Tailles de lot : le calcul utilise `OrderCalcProfit`, qui gère la devise du compte, le tick value et les contrats CFD
(XAUUSD, NAS100, BTCUSD…). En secours, il utilise `TICK_VALUE_LOSS / TICK_SIZE`. Il arrondit au `VOLUME_STEP` inférieur.
Avant chaque ordre, l'EA vérifie `SYMBOL_TRADE_STOPS_LEVEL` et choisit le mode de remplissage (FOK → IOC → RETURN) selon le symbole.

## 4. Réglages du testeur de stratégie
- **Modélisation : « Every tick based on real ticks »** (chaque tick sur ticks réels). C'est indispensable : le SL est petit (souvent < 0,5 ATR), donc OHLC M1 fausse le BE et le SL/TP dans la même bougie.
- **Délais** : « Random delay » ou 50–100 ms pour simuler le live (l'entrée se fait au marché).
- **Commission** : la renseigner dans les spécifications du symbole du testeur, ou utiliser le compte réel du courtier.
  Ordres de grandeur du scanner (`costs.py`) : FX ≈ 6 $/lot aller-retour, XAU 0,07 $/oz, crypto 5 bp.
- **Dépôt** 10 000 et levier réel du compte. Période : par ex. 2025-10-01 → 2026-09-30, comme `scripts/v3/backtest.py`.
- **Forward : 1/3**, pour valider sur la dernière tranche ce qui a été choisi sur les 2/3 précédents.
- **Optimisation** (algorithme génétique). Paramètres raisonnables :
  `InpZoneTF` (M15, M30, H1, H4), `InpMinStars` 3–5, `InpTpR` 1.5–3.0 (pas 0.5), `InpBeAtR` 0 / 1.0 / 1.5,
  `InpImpulseAtr` 0.8–1.5 (pas 0.1), `InpTrigEngulf` / `InpTrigPin`, `InpMaxSpreadPts`.
  **Critère : « Custom max »**. `OnTester()` renvoie PF × √trades / (1 + DD%/10) et vaut 0 sous 30 trades.
  Ce critère pénalise les réglages qui ne tiennent que sur quelques trades. Ne garder que ce qui reste correct en forward.
- Fichiers CSV : avec `InpCommonFiles=true`, ils vont dans `…\Terminal\Common\Files\`
  (`OBK3_<SYMBOLE>_<TF>_zones.csv` et `_trades.csv`), y compris pour les agents du testeur. Ils sont remis à zéro à chaque passe.
  Pendant une optimisation, plusieurs passes écrivent dans le même fichier : désactiver l'écriture n'est pas prévu, donc lire les CSV après une **passe unique**.

## 5. Lire le rapport
- *Profit factor*, *Expected payoff*, *Drawdown relatif* et le nombre de trades. La métrique à comparer avec le scanner est le **R moyen** : prendre `r_gross` dans `OBK3_*_trades.csv` (lignes EXIT).
  Le scanner donne environ 0R brut et un résultat négatif net de frais (cf. STRATEGY_V3.md §9). Si l'EA est nettement meilleur, chercher la cause avant de s'en réjouir.
- Lignes EXIT : `exit` = tp / sl / be_exit (SL touché après le passage au BE) / close (fin de test).
- `OBK3_*_zones.csv` contient une ligne par zone terminée (et les zones encore vivantes en fin de test) : état, nombre de touchers,
  score et étoiles au toucher (T L V F S), déclencheur, heure d'entrée UTC. `missed` = le déclencheur était dans la bougie OB+3,
  avant que la zone soit connue (voir §6). `skipped` = trade refusé (spread, lot, stops level, max trades). La raison est dans `note`.

## 6. Différences connues avec le scanner
1. **Rattrapage « missed »** : la zone n'est connue qu'à la clôture de OB+3 (fin de l'impulsion). Si le FVG est complet à OB+2, le backtest Python
   accepte un toucher et un déclencheur **dans** la bougie OB+3, donc déjà passés à ce moment-là (léger biais d'anticipation du scanner).
   L'EA les journalise en `missed` sans trader. Cela concerne environ 2 à 5 % des trades.
2. **Flux du courtier** : prix bid du courtier contre M1 Dukascopy/Binance/Yahoo dans le cache. Les OHLC diffèrent un peu, donc certaines zones et certains déclencheurs diffèrent.
3. **Heure serveur** : MT5 horodate à l'heure du serveur. La conversion vers l'heure de Paris (étoile Session, colonnes UTC) dépend de `InpSrvMode`.
   Dans le testeur, `TimeGMT()` n'est pas fiable : le mode Auto suppose **NY-close** (GMT+2 l'hiver, GMT+3 pendant l'heure d'été US), qui est le cas d'IC Markets, Pepperstone, FTMO, etc.
   Pour un courtier calé sur Paris, choisir `SRV_EU_DST` avec un décalage de 1. Pour un serveur en GMT pur, choisir `SRV_FIXED` avec 0.
4. **Bougies H4 / D / W** : MT5 les aligne sur l'heure serveur (minuit serveur = 22:00 ou 21:00 UTC), alors que le scanner rééchantillonne en UTC.
   Les zones H4/D/W ne sont donc **pas** les mêmes bougies. M5 à H1 sont alignées.
5. **NQ / NAS100** : le scanner utilise `NAS100` (Yahoo `NQ=F`, futures). Chez le courtier, ce sera USTEC, NAS100, US100.cash, NQ100… (CFD sur cash ou future, autres horaires).
   Comparer avec `--py-symbol NAS100`.
6. **Gestion** : stops et BE déclenchés tick par tick sur bid/ask réels. Le Python, lui, utilise le mid ± ½ spread modélisé et compte SL avant TP dans la même bougie.
   Le TP est calculé depuis le prix d'exécution, pas depuis la clôture.
7. **ATR** : l'ATR est amorcé sur `InpHistoryBars` (1000) bougies, contre tout l'historique en Python. L'écart est négligeable (< 1e-6 relatif mesuré).
8. **Fin de données** : le Python tronque la vie d'une zone à OB+302 bougies, ce qui donne parfois « waiting » au lieu de « expired ». Aucun effet sur les trades.

## 7. Contrôle de parité (Python)
`parity_check.py` rejoue en Python la logique **streaming** de l'EA, fonction par fonction : détection à la clôture de OB+3 sur une fenêtre de N bougies,
machine à états ACTIVE / WINDOW / WAIT_OUT, bougies LTF puis clôture HTF. Il la compare zone par zone avec le moteur de prod (`detect_zones` + `simulate_zone`) :
```
/tmp/obv/bin/python mt5/parity_check.py --symbol EURUSD --tf H1 --start 2026-01-01 --end 2026-07-01
```
Résultats sur le cache (début 2026, `--hist 500`) : zones et étoiles statiques identiques à 100 % ; les trades ont la **même heure d'entrée et le même déclencheur** :
| Symbole / TF | Zones v3 | Trades v3 | Identiques (EA) | missed |
|---|---|---|---|---|
| EURUSD H1 (mars–juin) | 161 | 22 | 21 | 1 |
| XAUUSD M15 (T1) | 446 | 54 | 50 | 4 |
| BTC H1 (T1) | 160 | 17 | 17 | 0 |
| NAS100 H4 (T1) | 41 | 1 | 1 | 0 |
| GBPJPY M30 (T1) | 228 | 27 | 25 | 2 |
| EURUSD M5 (T1) | 1602 | 248 | 237 | 11 |

Aucun trade n'existe d'un seul côté, à part les « missed » (§6.1).

**Comparer le CSV de l'EA avec le backtest Python** (même symbole, même TF, même période) :
1. `/tmp/obv/bin/python scripts/v3/backtest.py --start 2026-01-01 --end 2026-07-01 --symbols EURUSD --tfs H1 --out data/backtest/v3_mt5cmp`
2. Lancer l'EA dans le testeur sur la même période, avec `InpZoneTF=H1`, puis copier `Common\Files\OBK3_EURUSD_H1_zones.csv` dans le dépôt.
3. `/tmp/obv/bin/python mt5/parity_check.py --ea-csv OBK3_EURUSD_H1_zones.csv --py-csv data/backtest/v3_mt5cmp/zones.csv --symbol EURUSD --tf H1`
   (pour l'indice : `--py-symbol NAS100`). Le script affiche les zones communes ou présentes d'un seul côté, le nombre de trades et les heures d'entrée identiques.
   Le détail ligne par ligne est écrit dans `*.compare.csv`. Il faut s'attendre aux écarts du §6 : flux, heure serveur, H4+.

## 8. Compilation
Il n'y avait ni MetaEditor ni compilateur MQL5 sur la machine de développement : le code n'a **pas encore été compilé**.
Il a été relu pour l'API (CTrade, CopyRates par dates, OrderCalcProfit, ObjectCreate / ObjectSetInteger avec modificateur, FileOpen CSV `;`).
Si F7 signale une erreur, envoyer le message exact (ligne + texte) : la correction sera rapide.
