# Déploiement PythonAnywhere — OB Scanner v2

Compte : **skyhawk376**  
v1 (prototype) : `https://skyhawk376.pythonanywhere.com/` → dossier `/home/skyhawk376/ob-scanner`  
v2 (ce repo) : à cloner dans `/home/skyhawk376/ob-scanner-v2`

> **Free PA = une seule Web app / un seul domaine.**  
> Pour mettre v2 en ligne sur `skyhawk376.pythonanywhere.com`, il faut **changer le fichier WSGI** pour pointer vers v2.  
> Le code v1 reste sur le disque et peut être rétabli en 30 s en rebranchant l’ancien WSGI.

---

## Options

| Option | Effet |
|---|---|
| **A (recommandé pour Oscar)** | WSGI → `ob-scanner-v2/wsgi.py`. Le domaine sert le nouveau scanner 5★. v1 reste dans `~/ob-scanner`. |
| **B** | Garder v1 en prod ; tester v2 en local / tunnel / second compte PA. |
| **C** | Compte PA payant / second web app / domaine custom — hors free tier. |

Sous-chemin `/v2/` n’est **pas** supporté nativement par le free tier (une app = racine du domaine).

---

## 1. Clone sur PA (Consoles → Bash)

```bash
cd ~
git clone https://github.com/skyhawk376/ob-scanner-v2.git
# ou mise à jour :
cd ~/ob-scanner-v2 && git pull
```

## 2. Virtualenv + dépendances (slim free PA)

Le free PA (~512 Mo) ne tient pas `requirements.txt` complet (pyarrow/ccxt/yfinance).
Utiliser **`requirements-pa.txt`** (pickle cache, pas de fetch live Yahoo/Binance).

```bash
# Libérer de l’espace d’abord
rm -rf ~/.cache/pip
cd ~/ob-scanner-v2
rm -rf .venv
python3.12 -m venv .venv || python3.10 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install --no-cache-dir -r requirements-pa.txt
```

Dans l’onglet **Web** → **Virtualenv** :  
`/home/skyhawk376/ob-scanner-v2/.venv`

Sans pyarrow le cache utilise des `.pkl`. Uploader `data/cache/` depuis ta machine si besoin (whitelist sortante free limitée).

## 3. Brancher le WSGI (remplace v1 sur le domaine)

Onglet **Web** → **WSGI configuration file**  
(souvent `/var/www/skyhawk376_pythonanywhere_com_wsgi.py`)

Remplacer le contenu par :

```python
# Point to OB Scanner v2
import sys
path = "/home/skyhawk376/ob-scanner-v2"
if path not in sys.path:
    sys.path.insert(0, path)

from wsgi import application  # noqa: E402
```

Ou indiquer directement le Source code / WSGI file comme :  
`/home/skyhawk376/ob-scanner-v2/wsgi.py`  
(si l’UI PA le permet).

**Working directory** (si demandé) : `/home/skyhawk376/ob-scanner-v2`

## 4. Reload

Bouton vert **Reload** sur l’onglet Web.

Smoke :

- `https://skyhawk376.pythonanywhere.com/` → UI sombre Scanner  
- `https://skyhawk376.pythonanywhere.com/health` → `{"phase":"P5",...}`  
- Bouton **Scanner les OrderBlocks** (données = cache Parquet sous `data/cache/` ; premier scan peut être vide jusqu’à `fetch_candles`)

## 5. Données / cache (optionnel)

```bash
cd ~/ob-scanner-v2
source .venv/bin/activate
# Depuis une console Bash (si les hosts Yahoo/Binance/Kraken sont autorisés) :
python scripts/fetch_candles.py --tf H1 --quiet
python scripts/scan.py --tf H1 --quiet
```

Sur free PA, la whitelist sortante est limitée — Yahoo / OANDA / exchanges peuvent échouer. Dans ce cas, uploader un `data/cache/` prérempli (scp / upload) depuis cette machine.

## 6. Revenir à v1

Remettre le WSGI sur l’ancien projet :

```python
path = "/home/skyhawk376/ob-scanner"
# … puis import de l’ancien wsgi / server
```

ou le contenu d’origine de `/home/skyhawk376/ob-scanner/wsgi.py`, puis **Reload**.

---

## Fichiers clés v2

| Fichier | Rôle |
|---|---|
| `wsgi.py` | `ASGIMiddleware(FastAPI)` → `application` |
| `frontend/dist/` | Build prod (commité) servi par FastAPI StaticFiles |
| `requirements.txt` | Inclut `a2wsgi` |
| `data/cache/`, `data/results/` | Créés au démarrage si absents |

## Ne pas faire

- Ne pas écraser le dossier `~/ob-scanner` (v1).  
- Ne pas committer `.env` / tokens.  
- MCP stdio n’a pas de sens sur PA web ; garder MCP en local.
