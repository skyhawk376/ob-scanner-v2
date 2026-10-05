# Hébergement en ligne — notes (P5 / P7 light)

> **Prod recommandée : Fly.io always-on → voir `DEPLOY_FLY.md`.** PythonAnywhere free (`DEPLOY_PA.md`) = vitrine/rollback sans fetch live.

## Option A — un seul process (API + front buildé)

```bash
cd frontend && npm ci && npm run build && cd ..
docker compose up --build
# → http://HOST:8000/  (SPA) + /health + /scan …
```

Variables utiles (`.env`) : `OANDA_*`, `TELEGRAM_*`, `TELEGRAM_DRY_RUN`, `ENABLE_SCHEDULER`.

Persistance : volume `./data` (Parquet cache + SQLite + telegram log).

## Option B — Railway / Render / Fly

1. **Build** : `Dockerfile` à la racine (installe Python deps; copier `frontend/dist` — faire `npm run build` en CI avant `docker build`, ou multi-stage).
2. **Start** : `uvicorn app.api.main:app --app-dir backend --host 0.0.0.0 --port $PORT`
3. **Disk** : volume persistant pour `/app/data` (sinon le cache et SQLite repartent à zéro).
4. **Front** : soit servi par FastAPI (`frontend/dist`), soit un static site séparé pointant `VITE_API_URL=https://api.example.com`.
5. **Binance** : certains hébergeurs US bloquent Binance — le provider bascule déjà vers Kraken/Coinbase/yfinance.
6. **PythonAnywhere free** : whitelist de domaines limitée; préférer un VPS / Railway / Fly pour OANDA+Yahoo.

### Multi-stage Dockerfile (exemple)

```dockerfile
FROM node:20-alpine AS front
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt mcp
COPY backend ./backend
COPY symbols.yaml .
COPY --from=front /fe/dist ./frontend/dist
ENV PYTHONPATH=/app/backend TZ=Europe/Paris
CMD uvicorn app.api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}
```

## MCP (local only)

Le serveur MCP est **stdio** pour Claude Desktop sur la machine locale. Ne pas exposer MCP sur Internet sans auth.
