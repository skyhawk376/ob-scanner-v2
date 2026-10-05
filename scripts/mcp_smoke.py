#!/usr/bin/env python3
"""Smoke-test MCP tools in-process (no Claude Desktop required).

Usage:
  cd /workspace/ob-scanner-v2
  .venv/bin/python scripts/mcp_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.mcp.server import mcp  # noqa: E402
from app.mcp.tools_impl import tool_list_zones  # noqa: E402


async def main() -> int:
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    print("MCP tools:", ", ".join(names))
    assert "list_zones" in names
    assert "get_zone" in names
    assert "scan_now" in names
    assert "get_stats" in names
    assert "get_candles" in names
    assert "get_chart_svg" in names

    # Direct impl smoke (faster / clearer errors)
    raw = tool_list_zones(tf="H1", min_stars=4, limit=3)
    data = json.loads(raw)
    print(f"list_zones n={data.get('n')}")

    r = await mcp.call_tool("get_stats", {"tf": "H1"})
    print("get_stats ok", not r.is_error, "chars", len(r.content[0].text) if r.content else 0)

    if data.get("zones"):
        zid = data["zones"][0]["id"]
        r2 = await mcp.call_tool("get_zone", {"id": zid})
        print("get_zone", zid[:40], "…", "ok", not r2.is_error)
        r3 = await mcp.call_tool("get_chart_svg", {"zone_id": zid, "bars": 40})
        print("get_chart_svg ok", not r3.is_error)
        if r3.content:
            preview = json.loads(r3.content[0].text)
            print("  svg path:", preview.get("path"))
    else:
        print("no zones in DB — run scan/refresh first (skip get_zone/chart)")

    r4 = await mcp.call_tool("get_candles", {"symbol": "EURUSD", "tf": "H1", "n": 5})
    print("get_candles ok", not r4.is_error)

    # Lightweight scan on one group (may take a few seconds)
    r5 = await mcp.call_tool("scan_now", {"tf": "H1", "group": "METAUX", "min_stars": 4})
    print("scan_now METAUX ok", not r5.is_error)
    if r5.content:
        print(" ", r5.content[0].text[:200].replace("\n", " "))

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
