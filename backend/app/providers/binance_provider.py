"""Binance public klines (+ ccxt fallbacks when geo-blocked)."""
from __future__ import annotations

import time
from typing import Any

import httpx
import pandas as pd

from ..core.cache import normalize_ohlc
from ..core.config import Settings, get_settings
from .base import CandleProvider, CandlesResult

TF_BINANCE: dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D": "1d",
    "W": "1w",
}

# ccxt timeframe strings (same as Binance for these)
TF_CCXT = TF_BINANCE

# Map Binance USDT pairs to Kraken / Coinbase ids when needed
KRAKEN_MAP = {
    "BTCUSDT": "BTC/USDT",
    "ETHUSDT": "ETH/USDT",
    "SOLUSDT": "SOL/USDT",
    "XRPUSDT": "XRP/USDT",
    "BNBUSDT": "BNB/USDT",
    "DOGEUSDT": "DOGE/USDT",
    "ADAUSDT": "ADA/USDT",
    "AVAXUSDT": "AVAX/USDT",
    "LINKUSDT": "LINK/USDT",
    "TONUSDT": "TON/USDT",
    "DOTUSDT": "DOT/USDT",
    "LTCUSDT": "LTC/USDT",
    "BCHUSDT": "BCH/USDT",
    "TRXUSDT": "TRX/USDT",
    "SUIUSDT": "SUI/USDT",
}

COINBASE_MAP = {
    "BTCUSDT": "BTC/USD",
    "ETHUSDT": "ETH/USD",
    "SOLUSDT": "SOL/USD",
    "XRPUSDT": "XRP/USD",
    "BNBUSDT": "BNB/USD",
    "DOGEUSDT": "DOGE/USD",
    "ADAUSDT": "ADA/USD",
    "AVAXUSDT": "AVAX/USD",
    "LINKUSDT": "LINK/USD",
    "DOTUSDT": "DOT/USD",
    "LTCUSDT": "LTC/USD",
    "BCHUSDT": "BCH/USD",
    # TON / TRX / SUI may be missing on Coinbase — will fail and try next
    "TONUSDT": "TON/USD",
    "TRXUSDT": "TRX/USD",
    "SUIUSDT": "SUI/USD",
}


class BinanceProvider(CandleProvider):
    name = "binance"

    def __init__(self, settings: Settings | None = None, pause_sec: float = 0.05):
        self.settings = settings or get_settings()
        self.pause_sec = pause_sec
        self._last_call = 0.0
        self._binance_ok: bool | None = None  # None=unknown, False=blocked
        self._exchanges: dict[str, Any] = {}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.pause_sec:
            time.sleep(self.pause_sec - elapsed)
        self._last_call = time.monotonic()

    def _fetch_binance_rest(self, pair: str, interval: str, limit: int) -> pd.DataFrame:
        url = f"{self.settings.binance_base_url.rstrip('/')}/api/v3/klines"
        # Binance max 1000 per request; paginate if needed
        all_rows: list[list] = []
        end_time: int | None = None
        remaining = limit
        with httpx.Client(timeout=30.0) as client:
            while remaining > 0:
                batch = min(remaining, 1000)
                params: dict[str, Any] = {
                    "symbol": pair,
                    "interval": interval,
                    "limit": batch,
                }
                if end_time is not None:
                    params["endTime"] = end_time
                self._throttle()
                resp = client.get(url, params=params)
                if resp.status_code in (403, 451):
                    raise PermissionError(f"Binance geo-blocked ({resp.status_code})")
                if resp.status_code == 400:
                    raise ValueError(f"bad symbol/params: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                all_rows = data + all_rows
                # next page: older than first candle
                first_open = int(data[0][0])
                end_time = first_open - 1
                remaining -= len(data)
                if len(data) < batch:
                    break
        if not all_rows:
            return pd.DataFrame()
        rows = []
        for k in all_rows:
            rows.append(
                {
                    "ts": pd.to_datetime(int(k[0]), unit="ms", utc=True),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )
        df = pd.DataFrame(rows).set_index("ts")
        df = normalize_ohlc(df)
        # drop incomplete last bar heuristically? keep all; engine ignores incomplete later
        if limit and len(df) > limit:
            df = df.iloc[-limit:]
        return df

    def _get_ccxt(self, name: str):
        if name in self._exchanges:
            return self._exchanges[name]
        import ccxt

        klass = getattr(ccxt, name, None)
        if klass is None:
            raise ValueError(f"unknown ccxt exchange {name}")
        ex = klass({"enableRateLimit": True, "timeout": 30000})
        self._exchanges[name] = ex
        return ex

    def _fetch_ccxt(
        self, exchange_name: str, symbol: str, tf: str, limit: int
    ) -> pd.DataFrame:
        ex = self._get_ccxt(exchange_name)
        timeframe = TF_CCXT[tf]
        self._throttle()
        # ccxt max often 1000
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(limit, 1000))
        if not ohlcv:
            return pd.DataFrame()
        rows = [
            {
                "ts": pd.to_datetime(r[0], unit="ms", utc=True),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
            for r in ohlcv
        ]
        df = pd.DataFrame(rows).set_index("ts")
        return normalize_ohlc(df)

    def fetch(
        self,
        remote_id: str,
        tf: str,
        *,
        limit: int = 5000,
    ) -> CandlesResult:
        tf = tf.upper()
        pair = remote_id.upper().replace("/", "").replace("-", "")
        if not pair.endswith("USDT") and len(pair) <= 5:
            pair = f"{pair}USDT"
        if tf not in TF_BINANCE:
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=pd.DataFrame(),
                ok=False,
                error=f"unsupported tf {tf}",
            )
        interval = TF_BINANCE[tf]
        errors: list[str] = []

        # 1) Try Binance REST unless previously blocked
        if self._binance_ok is not False:
            try:
                df = self._fetch_binance_rest(pair, interval, limit)
                self._binance_ok = True
                if df.empty:
                    return CandlesResult(
                        symbol=remote_id,
                        tf=tf,
                        source=self.name,
                        df=df,
                        ok=False,
                        error="empty klines",
                    )
                return CandlesResult(
                    symbol=remote_id,
                    tf=tf,
                    source=self.name,
                    df=df,
                    ok=True,
                    meta={"via": "binance_rest", "interval": interval},
                )
            except PermissionError as e:
                self._binance_ok = False
                errors.append(str(e))
            except Exception as e:
                errors.append(f"binance: {e}")
                # soft-fail: still try fallbacks

        # 2) ccxt fallbacks (kraken, coinbase, …)
        chain = [
            x.strip()
            for x in self.settings.crypto_fallback_exchanges.split(",")
            if x.strip() and x.strip() != "binance"
        ]
        for ex_name in chain:
            try:
                if ex_name == "kraken":
                    sym = KRAKEN_MAP.get(pair, pair.replace("USDT", "/USDT"))
                elif ex_name == "coinbase":
                    sym = COINBASE_MAP.get(pair)
                    if not sym:
                        errors.append(f"coinbase: no mapping for {pair}")
                        continue
                else:
                    sym = pair.replace("USDT", "/USDT")
                df = self._fetch_ccxt(ex_name, sym, tf, limit)
                if df.empty:
                    errors.append(f"{ex_name}: empty")
                    continue
                return CandlesResult(
                    symbol=remote_id,
                    tf=tf,
                    source=f"{self.name}/{ex_name}",
                    df=df,
                    ok=True,
                    meta={"via": ex_name, "mapped": sym, "interval": interval},
                )
            except Exception as e:
                errors.append(f"{ex_name}: {e}")

        return CandlesResult(
            symbol=remote_id,
            tf=tf,
            source=self.name,
            df=pd.DataFrame(),
            ok=False,
            error="; ".join(errors)[:400] or "all crypto sources failed",
        )
