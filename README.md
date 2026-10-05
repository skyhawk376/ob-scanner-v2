# OB 5-star Scanner (v2)

Kasper-style Order Block scanner rebuilt from scratch (see `/workspace/ob-scanner/PLAN.md`).

This folder is a **sibling** of the live prototype (`/workspace/ob-scanner`, PythonAnywhere).
It does **not** replace or break the existing app.

**Phase:** P5 — MCP server (Claude Desktop) + hosting notes (P0–P5).

Timezone default: **Europe/Paris**.

---

## Stack (P0)

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ / FastAPI |
| Data | OANDA v20 (FX/metals/energy/NAS100), Binance public klines + ccxt fallbacks, yfinance |
| Cache | Parquet under `data/cache/{SYMBOL}_{TF}.parquet` |
| Front | Placeholder only (React+Vite arrives in P2) |

---

## Setup

```bash
cd /workspace/ob-scanner-v2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional — fill OANDA keys if you have them
```

### OANDA (optional but recommended for FX / metals / energy / NAS100)

1. Create a free **practice** account at https://www.oanda.com/
2. In the account hub → **Manage API Access** → generate a personal access token
3. Copy your practice account ID
4. Put them in `.env`:

```env
OANDA_API_KEY=your_token_here
OANDA_ACCOUNT_ID=your-account-id
OANDA_ENV=practice
```

Without a key, the fetcher **automatically falls back to yfinance** for instruments that have a Yahoo ticker (FX `EURUSD=X`, gold `GC=F`, etc.). OANDA-only symbols without a `yf` mapping will fail until a key is set.

### Binance / crypto

Public REST, **no API key**. If Binance is geo-blocked (HTTP 403/451), the provider tries **Kraken** then **Coinbase** via `ccxt`, then yfinance (`BTC-USD`, …).

---

## Fetch candles (success criterion for P0)

Load OHLC for the full watchlist on at least one timeframe, write Parquet, print ok/fail:

```bash
# Full list, H1 only (~115 symbols) — takes a few minutes (yfinance throttling)
.venv/bin/python scripts/fetch_candles.py --tf H1

# Faster smoke test
.venv/bin/python scripts/fetch_candles.py --symbols XAUUSD,EURUSD,BTC,AAPL --tf H1,D

# One group
.venv/bin/python scripts/fetch_candles.py --group CRYPTO --tf H1,H4

# Quiet progress dots
.venv/bin/python scripts/fetch_candles.py --tf H1 --quiet
```

Cache files land in `data/cache/`. Re-running merges idempotently on timestamp.

### API

```bash
.venv/bin/uvicorn app.api.main:app --app-dir backend --reload --port 8000
# GET  http://127.0.0.1:8000/health
# GET  http://127.0.0.1:8000/symbols
# POST http://127.0.0.1:8000/fetch?tf=H1
```

---

## Scan Order Blocks (Phase 1)

```bash
# Full watchlist H1 (uses Parquet cache from P0)
.venv/bin/python scripts/scan.py --tf H1

# Filter + lower threshold
.venv/bin/python scripts/scan.py --tf H1 --group METAUX,FOREX --min-score 3

# Unit tests
.venv/bin/python -m pytest tests/ -q
```

Results land in `data/results/zones.sqlite` and `data/results/zones_H1.json`.

API:

```bash
.venv/bin/uvicorn app.api.main:app --app-dir backend --port 8000
# POST /scan?tf=H1&min_score=4
# GET  /zones?tf=H1&min_score=4
```

Engine rules (user mode): virgin OB = hard filter; stars = FVG, trend, Fib 0.5, no distal liquidity, London/NY session (Paris). Default display score ≥ 4. XAUUSD pinned.

## MCP (Phase 5)

```bash
.venv/bin/python scripts/mcp_smoke.py
# Claude Desktop launches:
#   command: <repo>/.venv/bin/python
#   args: ["-m", "app.mcp.server"]
#   cwd: <repo>/backend
```

Tools: `list_zones`, `get_zone`, `scan_now`, `get_stats`, `get_candles`, `get_chart_svg` (SVG; no PNG dep).

UI tab **Claude / MCP** shows live catalog from `GET /mcp/tools` + copy-paste Claude Desktop JSON.

Hosting: see `DEPLOY.md`, `Dockerfile`, `docker-compose.yml`.

## Lifecycle & Telegram (P3–P4)


```bash
# Classify zones from cached candles (history backfill recommended once)
.venv/bin/python scripts/refresh_status.py --tf H1 --history

# Telegram dry-run (no token required)
.venv/bin/python scripts/telegram_dryrun.py
# → data/results/telegram_dryrun.log

# Live Telegram: set in .env then TELEGRAM_DRY_RUN=false
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

API: `POST /refresh`, `GET /stats`, `POST /telegram/digest`, `GET /mcp/tools`.

UI tabs **OB Touchés** / **Réaction** read lifecycle statuses; **Claude / MCP** is a P5 stub.

## Interface (Phase 2)


French dark UI: tabs Scanner / OB Touchés / Réaction / Claude·MCP, filtres TF & groupes,
bouton **Scanner les OrderBlocks**, mosaïque de mini-graphiques (ZONE ACHAT / ZONE VENTE).

```bash
# Terminal 1 — API
cd /workspace/ob-scanner-v2
.venv/bin/uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000

# Terminal 2 — UI (Vite proxies /api → :8000)
cd /workspace/ob-scanner-v2/frontend
npm install
npm run dev
# → http://127.0.0.1:5173/
```

Optional: `VITE_API_URL=http://127.0.0.1:8000` to call the API without the Vite proxy.

Screenshots: `data/results/ui-scanner.png`, `data/results/ui-mosaic.png`.

## Symbol groups

 (`symbols.yaml`)

| Group | Count | Primary source |
|---|---|---|
| NQ100 | 62 (NAS100 + 61 stocks) | OANDA for NAS100 if keyed, else yfinance; stocks → yfinance |
| Métaux | 5 (XAUUSD first) | OANDA → yfinance futures |
| Énergie | 5 | OANDA where available → yfinance (`CL=F`, `RB=F`, …) |
| Forex | 28 | OANDA → yfinance `=X` |
| Crypto | 15 | Binance → Kraken/Coinbase → yfinance |
| **Total** | **115** | |

---

## What needs keys?

| Source | Key required? |
|---|---|
| yfinance | No |
| Binance / Kraken / Coinbase public | No |
| OANDA | Yes (`OANDA_API_KEY`) for native CFD prices; optional thanks to yfinance fallback |

Telegram notifications are deferred (P4).

---

## Layout

```
ob-scanner-v2/
  symbols.yaml
  requirements.txt
  .env.example
  README.md
  STATUS.md
  backend/app/
    api/main.py          # FastAPI
    core/                # config, symbols, cache, fetcher, scanner, store
    engine/              # pure OB detection + ★1-★5
    providers/           # oanda, binance, yfinance
  data/cache/            # Parquet OHLC
  scripts/fetch_candles.py
  scripts/scan.py
  tests/
  frontend/              # React + Vite + Tailwind + lightweight-charts
```

## Next (P6–P7)

Backtest / calibration · packaging polish · analyse IA optionnelle.
