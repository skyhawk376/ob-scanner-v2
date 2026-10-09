"""Shared tool catalog for FastAPI /mcp/tools and docs."""

TOOL_CATALOG = [
    {
        "name": "list_zones",
        "args": ["tf?", "group?", "min_stars?", "status?"],
        "description": "Liste les zones OB (filtres TF, groupe, score, statut).",
    },
    {
        "name": "get_zone",
        "args": ["id"],
        "description": "Détail d'une zone par id stable.",
    },
    {
        "name": "scan_now",
        "args": ["tf", "group?"],
        "description": "Lance un scan OB sur le cache Parquet (écriture SQLite).",
    },
    {
        "name": "get_stats",
        "args": ["tf?"],
        "description": "Stats v3 (R net, WR, par TF/groupe, entrées/jour).",
    },
    {
        "name": "get_candles",
        "args": ["symbol", "tf", "n?"],
        "description": "OHLC depuis le cache Parquet.",
    },
    {
        "name": "get_chart_svg",
        "args": ["zone_id", "bars?"],
        "description": "Mini-graphique SVG (bougies + zone) sans dépendance lourde.",
    },
]
