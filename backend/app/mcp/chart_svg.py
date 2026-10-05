"""Minimal SVG candlestick chart + OB zone (stdlib only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def render_zone_chart_svg(
    candles: list[dict[str, float]],
    zone: dict[str, Any],
    *,
    width: int = 640,
    height: int = 280,
) -> str:
    if not candles:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120">'
            '<text x="20" y="60" fill="#a1a1aa">Pas de bougies</text></svg>'
        )

    pad_l, pad_r, pad_t, pad_b = 48, 16, 28, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    highs = [c["high"] for c in candles] + [float(zone["high"]), float(zone["low"])]
    lows = [c["low"] for c in candles] + [float(zone["high"]), float(zone["low"])]
    ymin, ymax = min(lows), max(highs)
    if ymax <= ymin:
        ymax = ymin + 1.0
    span = ymax - ymin

    def y(price: float) -> float:
        return pad_t + (1.0 - (price - ymin) / span) * plot_h

    n = len(candles)
    slot = plot_w / max(n, 1)
    body_w = max(1.0, slot * 0.6)

    bull = zone.get("direction") == "bull"
    zone_fill = "rgba(34,197,94,0.25)" if bull else "rgba(239,68,68,0.25)"
    zone_stroke = "#22c55e" if bull else "#ef4444"
    label = "ZONE ACHAT" if bull else "ZONE VENTE"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" style="background:#0c0c0e">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#0c0c0e"/>',
        f'<text x="{pad_l}" y="18" fill="#e4e4e7" font-size="12" font-family="sans-serif">'
        f'{escape(str(zone.get("symbol")))} {escape(str(zone.get("tf")))} · '
        f'score {zone.get("score")} · {escape(label)}</text>',
    ]

    # zone rectangle across full width (price band)
    y1, y2 = y(float(zone["high"])), y(float(zone["low"]))
    top, bot = min(y1, y2), max(y1, y2)
    parts.append(
        f'<rect x="{pad_l}" y="{top}" width="{plot_w}" height="{max(bot - top, 2)}" '
        f'fill="{zone_fill}" stroke="{zone_stroke}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{pad_l + 4}" y="{top + 12}" fill="{zone_stroke}" font-size="10" '
        f'font-family="sans-serif" font-weight="700">{escape(label)}</text>'
    )

    for i, c in enumerate(candles):
        x_mid = pad_l + slot * i + slot / 2
        up = c["close"] >= c["open"]
        color = "#22c55e" if up else "#ef4444"
        y_h, y_l = y(c["high"]), y(c["low"])
        y_o, y_c = y(c["open"]), y(c["close"])
        parts.append(
            f'<line x1="{x_mid}" y1="{y_h}" x2="{x_mid}" y2="{y_l}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
        body_top, body_bot = min(y_o, y_c), max(y_o, y_c)
        parts.append(
            f'<rect x="{x_mid - body_w / 2}" y="{body_top}" width="{body_w}" '
            f'height="{max(body_bot - body_top, 1)}" fill="{color}"/>'
        )

    # price labels
    parts.append(
        f'<text x="4" y="{y(ymax) + 4}" fill="#71717a" font-size="9">{ymax:.4g}</text>'
    )
    parts.append(
        f'<text x="4" y="{y(ymin) + 4}" fill="#71717a" font-size="9">{ymin:.4g}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def write_zone_chart(
    path: Path,
    candles: list[dict[str, float]],
    zone: dict[str, Any],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    svg = render_zone_chart_svg(candles, zone)
    path.write_text(svg, encoding="utf-8")
    return path
