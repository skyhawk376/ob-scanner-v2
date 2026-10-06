# TradingView — OB Scanner (Filtre B)

## Fichiers
- `OB_Scanner_FiltreB.pine` : indicateur Pine v6 (overlay) qui recalcule sur le graphique les OB du scanner (mêmes règles, mêmes étoiles, même cycle de vie).
- `pine_reference.py` : portage Python ligne à ligne de la logique Pine (sert à vérifier la parité).
- `parity_check.py` : compare `pine_reference` au moteur du scanner (`backend/app/engine/detect.py` + `core/lifecycle.py`).
- `export_zones_pine.py` : génère un indicateur Pine *statique* avec les zones live d'un symbole lues sur l'API prod (`GET /zones`, lecture seule).
- `examples/XAUUSD_live_zones.pine` : exemple de sortie.

## Installation TradingView
1. Ouvrir un graphique (de préférence le flux utilisé par le scanner : `COMEX:GC1!` pour XAUUSD, `COMEX:SI1!` pour XAGUSD, `FX:EURUSD`/broker pour le forex, `BINANCE:BTCUSDT` pour la crypto).
2. Bas de l'écran → **Pine Editor** → menu → **Créer un nouvel indicateur**.
3. Tout effacer, coller le contenu de `OB_Scanner_FiltreB.pine`, **Enregistrer**, puis **Ajouter au graphique**.
4. Alertes : **Alerte (⏰)** → Condition = *OB Filtre B* → **Toute fonction alert()** (message complet avec entrée/SL/TP), ou la condition « Toucher OB (zone vierge ≥ min ★) ».

## Entrées principales
Étoiles minimum (4), zones actives/vierges (oui), historique touchées/expirées (non), nombre max de zones (30), ligne d'entrée (mid, pointillés), lignes SL/TP 2R, labels, couleurs + transparence, HTF optionnel (`request.security` avec `[1]` + `lookahead_on` → pas de repaint), alertes on/off.

## Parité (moteur Python ↔ scanner, scan simulé à chaque bougie)
- Cache prod (8 symboles × 7 TF) : 1732 zone×scan, 100 % identiques (zones, étoiles, niveaux).
- Données longues 5000 bougies (M5, M15, H1, H4 ; XAUUSD, EURUSD, GBPUSD, GBPJPY, USDJPY, BTC, ETH) : 2744 zone×scan, 100 %.
- Live vs `/zones` prod : 4/4 zones actives.
- Historique/cycle de vie : 34/36 zones, statuts 100 % ; les 2 écarts sont de vieilles zones déjà expirées que le scanner re-liste quand un pivot sort de sa fenêtre de 500 bougies (jamais actives).

Relancer : `python tradingview/parity_check.py --dir <dossier json bougies> --scans 300`.

## Limites
- Flux : le scanner utilise Yahoo (GC=F, SI=F, EURUSD=X) et Binance ; un autre flux TradingView (spot OANDA, autre broker) donne des bougies différentes → zones légèrement différentes.
- H4 : le scanner agrège en tranches 00:00 UTC ; certains symboles TradingView (futures/FX) alignent le H4 sur la session.
- ★5 session : heure de Paris de l'ouverture de bougie (dépend aussi de l'alignement H4/D/W).
- Historique prod reconstruit chaque jour à 06:30 avec le recul ; l'historique Pine est figé au toucher.
- Le Pine n'a pas été compilé dans TradingView depuis ce poste (analyse syntaxique + relecture seulement).
