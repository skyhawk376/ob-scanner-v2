"""Load and normalize instruments from symbols.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Instrument:
    id: str
    group: str  # NQ100 | METAUX | ENERGIE | FOREX | CRYPTO
    primary: str  # oanda | binance | yfinance
    oanda: str | None = None
    yf: str | None = None
    bn: str | None = None  # Binance pair e.g. BTCUSDT
    priority: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def fallbacks(self) -> list[str]:
        """Ordered fallback providers after primary."""
        order = []
        if self.primary != "yfinance" and self.yf:
            order.append("yfinance")
        if self.primary != "oanda" and self.oanda:
            order.append("oanda")
        if self.primary != "binance" and self.bn:
            order.append("binance")
        return order


def _fx_oanda(pair: str) -> str:
    """EURUSD -> EUR_USD."""
    pair = pair.upper().replace("/", "").replace("_", "")
    if len(pair) == 6:
        return f"{pair[:3]}_{pair[3:]}"
    return pair


def _fx_yf(pair: str) -> str:
    """EURUSD -> EURUSD=X."""
    pair = pair.upper().replace("/", "").replace("_", "")
    return f"{pair}=X"


def _crypto_bn(coin: str) -> str:
    c = coin.upper().replace("USDT", "").replace("-USD", "")
    return f"{c}USDT"


def _crypto_yf(coin: str) -> str:
    c = coin.upper().replace("USDT", "").replace("-USD", "")
    return f"{c}-USD"


def load_instruments(path: Path | str) -> list[Instrument]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    out: list[Instrument] = []

    # --- NQ100 ---
    nq = raw.get("NQ100") or {}
    for item in nq.get("index") or []:
        if isinstance(item, str):
            item = {"id": item}
        sid = item["id"]
        out.append(
            Instrument(
                id=sid,
                group="NQ100",
                primary="oanda" if item.get("oanda") else "yfinance",
                oanda=item.get("oanda"),
                yf=item.get("yf", "^NDX" if sid == "NAS100" else sid),
                priority=item.get("priority", 0),
            )
        )
    for ticker in nq.get("stocks") or []:
        t = ticker if isinstance(ticker, str) else ticker["id"]
        out.append(
            Instrument(
                id=t,
                group="NQ100",
                primary="yfinance",
                yf=t,
            )
        )

    # --- METAUX ---
    for item in raw.get("METAUX") or []:
        if isinstance(item, str):
            item = {"id": item}
        out.append(
            Instrument(
                id=item["id"],
                group="METAUX",
                primary="oanda" if item.get("oanda") else "yfinance",
                oanda=item.get("oanda"),
                yf=item.get("yf"),
                priority=int(item.get("priority", 0)),
            )
        )

    # --- ENERGIE ---
    for item in raw.get("ENERGIE") or []:
        if isinstance(item, str):
            item = {"id": item}
        has_oanda = bool(item.get("oanda"))
        out.append(
            Instrument(
                id=item["id"],
                group="ENERGIE",
                primary="oanda" if has_oanda else "yfinance",
                oanda=item.get("oanda"),
                yf=item.get("yf"),
                priority=int(item.get("priority", 0)),
            )
        )

    # --- FOREX ---
    for pair in raw.get("FOREX") or []:
        if isinstance(pair, dict):
            pid = pair["id"]
            oanda = pair.get("oanda") or _fx_oanda(pid)
            yf = pair.get("yf") or _fx_yf(pid)
        else:
            pid = str(pair)
            oanda = _fx_oanda(pid)
            yf = _fx_yf(pid)
        out.append(
            Instrument(
                id=pid,
                group="FOREX",
                primary="oanda",
                oanda=oanda,
                yf=yf,
            )
        )

    # --- CRYPTO ---
    for coin in raw.get("CRYPTO") or []:
        if isinstance(coin, dict):
            cid = coin["id"]
            bn = coin.get("bn") or _crypto_bn(cid)
            yf = coin.get("yf") or _crypto_yf(cid)
        else:
            cid = str(coin)
            bn = _crypto_bn(cid)
            yf = _crypto_yf(cid)
        out.append(
            Instrument(
                id=cid,
                group="CRYPTO",
                primary="binance",
                bn=bn,
                yf=yf,
            )
        )

    # Stable order: priority desc within group, then id; XAUUSD first overall via priority
    group_order = {"METAUX": 0, "NQ100": 1, "ENERGIE": 2, "FOREX": 3, "CRYPTO": 4}
    out.sort(key=lambda i: (group_order.get(i.group, 9), -i.priority, i.id))
    return out


def count_by_group(instruments: list[Instrument]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in instruments:
        counts[i.group] = counts.get(i.group, 0) + 1
    return counts
