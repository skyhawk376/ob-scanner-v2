"""Resolve providers and instrument list."""
from __future__ import annotations

from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.symbols import Instrument, load_instruments
from .base import CandleProvider
from .binance_provider import BinanceProvider
from .oanda_provider import OandaProvider
from .yfinance_provider import YFinanceProvider


class ProviderHub:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.yfinance = YFinanceProvider(pause_sec=self.settings.yfinance_pause_sec)
        self.oanda = OandaProvider(self.settings, pause_sec=self.settings.oanda_pause_sec)
        self.binance = BinanceProvider(self.settings, pause_sec=self.settings.binance_pause_sec)

    def get(self, name: str) -> CandleProvider:
        name = name.lower()
        if name in ("yf", "yfinance", "yahoo"):
            return self.yfinance
        if name == "oanda":
            return self.oanda
        if name in ("binance", "bn", "crypto"):
            return self.binance
        raise KeyError(f"unknown provider {name}")

    def remote_id(self, inst: Instrument, provider_name: str) -> str | None:
        p = provider_name.lower()
        if p in ("yf", "yfinance", "yahoo"):
            return inst.yf
        if p == "oanda":
            return inst.oanda
        if p in ("binance", "bn", "crypto"):
            return inst.bn
        return None

    def provider_chain(self, inst: Instrument) -> list[str]:
        """Primary then fallbacks that have a remote id."""
        chain = [inst.primary] + [
            f for f in inst.fallbacks if self.remote_id(inst, f)
        ]
        # de-dupe preserving order
        seen: set[str] = set()
        out: list[str] = []
        for c in chain:
            if c not in seen and self.remote_id(inst, c):
                seen.add(c)
                out.append(c)
        # Always allow yfinance last if we somehow have a yf id
        if inst.yf and "yfinance" not in seen:
            out.append("yfinance")
        return out


def get_provider_for_symbol(inst: Instrument, settings: Settings | None = None) -> str:
    return inst.primary


def load_instruments_from_settings(settings: Settings | None = None) -> list[Instrument]:
    settings = settings or get_settings()
    return load_instruments(Path(settings.symbols_yaml))


# re-export
__all__ = [
    "ProviderHub",
    "get_provider_for_symbol",
    "load_instruments",
    "load_instruments_from_settings",
]
