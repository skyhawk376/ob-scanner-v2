# STATUS — OB 5-star scanner v2

**Date:** 2026-10-05 (Europe/Paris)  
**Phase:** P5 (MCP) — **complete** (P0–P5)  
**Path:** `/workspace/ob-scanner-v2` (prototype untouched; no commit/push)

## How to run MCP

```bash
cd /workspace/ob-scanner-v2
# Smoke (in-process)
.venv/bin/python scripts/mcp_smoke.py

# Stdio server (what Claude Desktop launches)
cd backend && ../.venv/bin/python -m app.mcp.server
```

Claude Desktop — merge into `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ob-scanner": {
      "command": "/workspace/ob-scanner-v2/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/workspace/ob-scanner-v2/backend"
    }
  }
}
```

(Live snippet also on UI tab **Claude / MCP** and `GET /mcp/tools`.)

## MCP tools

| Tool | Role |
|---|---|
| `list_zones` | Filter tf / group / min_stars / status |
| `get_zone` | Full zone by id |
| `scan_now` | Scan Parquet cache → SQLite |
| `get_stats` | Lifecycle stats |
| `get_candles` | OHLC from cache |
| `get_chart_svg` | SVG chart (no matplotlib; PNG skipped) |

Smoke: **SMOKE OK** — all 6 tools callable; sample SVG under `data/results/charts/`.

## Hosting

See `DEPLOY.md` + `Dockerfile` / `docker-compose.yml` (API + optional `frontend/dist` on `:8000`).

## Gaps vs original UI vision

- No fullscreen chart click / WebSocket live push
- No Telegram `sendPhoto` of charts (SVG file exists for MCP)
- No M15/M5 confirmation monitor
- MCP is **stdio local** only (not remote HTTP MCP)
- PNG charts not implemented (SVG alternative)
- Backtest HTML report (P6) not started

## Phases done

P0 data · P1 engine · P2 UI · P3 lifecycle · P4 Telegram · **P5 MCP**
