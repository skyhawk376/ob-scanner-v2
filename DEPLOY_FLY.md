# Déploiement Fly.io (always-on) — OB Scanner v2

**Pourquoi Fly :** `fly.toml` + `Dockerfile` déjà prêts, région **cdg (Paris)**, ~4 $/mois,
`flyctl` déjà authentifié sur la box (org `Rafale` / slug `personal`).
**Blocage précédent (5 oct. 18:00) :** `fly apps create` → `422 "We need your payment information
to continue! Add a credit card or buy credit"` (org `billing_status = SOURCE_REQUIRED`). Fly n'a plus de
free tier pour les nouvelles orgs → bascule PythonAnywhere free. **Seule action requise d'Oscar :
ajouter une carte (ou acheter du crédit) sur Fly.**

Ce que fait l'image (1 machine, 1 worker uvicorn) :

| Job (APScheduler in-process) | Fréquence |
|---|---|
| `pipeline` : fetch H1 (Yahoo/Binance/Kraken/Coinbase) → scan → refresh lifecycle (+ notif Telegram si activé) | toutes les `FETCH_INTERVAL_MIN` (15) min |
| `bootstrap` : même pipeline 10 s après le boot si cache vide ou > 2 h | au démarrage |
| `history_daily` : refresh `--history` (Touches / Réaction) | 06:30 Paris |
| digests Telegram | 07:45 / 14:15 Paris |

Volume `/data` (cache + `zones.sqlite` + `pipeline_status.json`). Test local : 115/115 symboles en ~55 s,
pic RAM ~210 Mo → 512 Mo OK.

## 0. Prérequis (Oscar, 2 min)

1. https://fly.io/dashboard/rafale/billing → **Add payment method** (ou *Buy credits*, ex. 25 $ prépayé).
2. Optionnel : vérifier que l'org « Rafale » est bien ton compte (email du compte Fly).

## 1. Déploiement (agent ou Oscar, depuis la box)

```bash
cd /workspace/ob-scanner-v2-fly          # branche feat/always-on-fly
export PATH="$HOME/.fly/bin:$PATH"
fly apps create ob-scanner-v2 --org personal      # si nom pris : ob-scanner-v2-oscar (+ changer app= dans fly.toml)
fly volumes create ob_data --region cdg --size 1 -a ob-scanner-v2 -y
fly deploy --ha=false                              # 1 seule machine (volume + scheduler unique)
```

Secrets (optionnels, jamais dans le repo) :

```bash
fly secrets set OANDA_API_KEY=... OANDA_ACCOUNT_ID=... -a ob-scanner-v2        # sinon Yahoo pour FX/métaux
fly secrets set TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... -a ob-scanner-v2   # puis TELEGRAM_DRY_RUN=false
```

## 2. Smoke

```bash
curl -fsS https://ob-scanner-v2.fly.dev/healthz            # {"status":"ok"}  (check Fly)
curl -fsS https://ob-scanner-v2.fly.dev/health | jq '.status,.cache_age_sec,.pipeline'
curl -fsS https://ob-scanner-v2.fly.dev/jobs/status | jq
curl -fsS -X POST https://ob-scanner-v2.fly.dev/fetch?tf=H1   # 202 → pipeline en arrière-plan
fly logs -a ob-scanner-v2 | grep -E "scheduler|pipeline"
```

`/health.status` = `stale` si dernière bougie H1 > 3 h (pipeline en panne) ; `/healthz` reste léger
pour que Fly ne redémarre pas la machine pendant un fetch.

### Optionnel : reprendre l'historique lifecycle existant

```bash
fly ssh sftp shell -a ob-scanner-v2
put /workspace/ob-scanner-v2/data/results/zones.sqlite /data/results/zones.sqlite
# puis: fly machine restart
```

## 3. Domaine

- URL nouvelle : `https://ob-scanner-v2.fly.dev`.
- `skyhawk376.pythonanywhere.com` est un sous-domaine PA : impossible de le pointer vers Fly.
  Il reste en ligne (v2 slim) = **rollback immédiat**.
- Domaine perso (optionnel, ~10 €/an) : `fly certs add scanner.mondomaine.fr -a ob-scanner-v2` + CNAME.

## 4. Rollback / arrêt

- PA v2 n'est **pas modifié** (`wsgi.py` inchangé : scheduler off, `/fetch` → 501).
- Couper Fly : `fly scale count 0 -a ob-scanner-v2` (volume conservé, ~0,15 $/mois)
  ou `fly apps destroy ob-scanner-v2` (tout supprimé, 0 $).
- Revenir à une release : `fly releases -a ob-scanner-v2` puis `fly deploy --image <image précédente>`.

## 5. Variables

| Var | Défaut image | Rôle |
|---|---|---|
| `ENABLE_SCHEDULER` | `true` | démarre APScheduler |
| `ENABLE_FETCH` | `true` | fetch live (sinon `/fetch` → 501) |
| `FETCH_INTERVAL_MIN` | `15` | période du pipeline (min 5) |
| `FETCH_TFS` | `H1` | TF fetchées (`H1,H4,D`) |
| `FETCH_LIMIT` / `BOOTSTRAP_LIMIT` | `300` / `800` | barres par série |
| `CACHE_DIR` / `RESULTS_DIR` | `/data/cache` / `/data/results` | sur le volume |
| `TELEGRAM_DRY_RUN` | `true` | `false` + secrets pour envoyer |
