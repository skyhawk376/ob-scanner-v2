#!/usr/bin/env python3
"""OB Scanner MCP server (stdio) — Claude Desktop / Claude Code.

Run:
  /workspace/ob-scanner-v2/.venv/bin/python -m app.mcp.server

From repo with PYTHONPATH=backend, or cwd=backend.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend package root is on path when launched as -m app.mcp.server
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from mcp.server.mcpserver import MCPServer

from app.mcp.tools_impl import (
    tool_get_candles,
    tool_get_chart_svg,
    tool_get_stats,
    tool_get_zone,
    tool_list_zones,
    tool_scan_now,
)

mcp = MCPServer(
    name="ob-scanner",
    title="OB 5-star Scanner",
    instructions=(
        "Scanner Order Blocks v3 « Kasper » (Europe/Paris) : OB + FVG obligatoire, 5 étoiles "
        "(Tendance, Liquidité prise, Jamais touché, Fibo 0.5, Session), ≥4★, entrée sur bougie de "
        "retournement en TF inférieure, SL au-delà de l'OB, TP +2R, SL au point d'entrée à +1R. "
        "Outils en lecture / scan local uniquement — aucun passage d'ordre. "
        "Préférez list_zones puis get_zone; XAUUSD est prioritaire."
    ),
    version="3.0.0",
)


@mcp.tool(description="Liste les zones OB filtrées (tf, group/category, min_stars, status).")
def list_zones(
    tf: str | None = None,
    group: str | None = None,
    min_stars: int = 4,
    status: str | None = None,
    limit: int = 50,
) -> str:
    """Filters: tf=M5|M15|M30|H1|H4|D|W, group=NQ100|METAUX|ENERGIE|FOREX|CRYPTO, status=active|touchee|en_position|tp|sl|be|invalidee|expiree."""
    return tool_list_zones(tf=tf, group=group, min_stars=min_stars, status=status, limit=limit)


@mcp.tool(description="Détail complet d'une zone par id (symbole|TF|direction|ts).")
def get_zone(id: str) -> str:
    return tool_get_zone(id)


@mcp.tool(description="Lance un scan OB maintenant sur le cache (tf, group optionnel).")
def scan_now(tf: str = "H1", group: str | None = None, min_stars: int = 4) -> str:
    return tool_scan_now(tf=tf, group=group, min_stars=min_stars)


@mcp.tool(description="Statistiques v3 : trades réalistes (R net de frais), WR, par TF/groupe, entrées/jour, backtest.")
def get_stats(tf: str | None = None) -> str:
    return tool_get_stats(tf=tf)


@mcp.tool(description="Bougies OHLC depuis le cache Parquet.")
def get_candles(symbol: str, tf: str = "H1", n: int = 100) -> str:
    return tool_get_candles(symbol=symbol, tf=tf, n=n)


@mcp.tool(description="Génère un mini-graphique SVG (zone + bougies). Alternative légère à PNG.")
def get_chart_svg(zone_id: str, bars: int = 80) -> str:
    return tool_get_chart_svg(zone_id=zone_id, bars=bars)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
