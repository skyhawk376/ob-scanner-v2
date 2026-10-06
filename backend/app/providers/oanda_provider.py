"""OANDA v20 candles adapter (practice/live). Falls back gracefully if no key."""
from __future__ import annotations

import time
from typing import Any

import httpx
import pandas as pd

from ..core.cache import normalize_ohlc
from ..core.config import Settings, get_settings
from .base import CandleProvider, CandlesResult

# OANDA granularity codes
TF_OANDA: dict[str, str] = {
    "M5": "M5",
    "M15": "M15",
    "M30": "M30",
    "H1": "H1",
    "H4": "H4",
    "D": "D",
    "W": "W",
}


class OandaProvider(CandleProvider):
    name = "oanda"

    def __init__(self, settings: Settings | None = None, pause_sec: float = 0.05):
        self.settings = settings or get_settings()
        self.pause_sec = pause_sec
        self._last_call = 0.0
        self._client: httpx.Client | None = None

    @property
    def configured(self) -> bool:
        return self.settings.oanda_configured

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.pause_sec:
            time.sleep(self.pause_sec - elapsed)
        self._last_call = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.oanda_api_key}",
            "Accept-Datetime-Format": "RFC3339",
            "Content-Type": "application/json",
        }

    def fetch(
        self,
        remote_id: str,
        tf: str,
        *,
        limit: int = 5000,
    ) -> CandlesResult:
        tf = tf.upper()
        if not self.configured:
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=pd.DataFrame(),
                ok=False,
                error="OANDA_API_KEY not set (use yfinance fallback)",
            )
        if tf not in TF_OANDA:
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=pd.DataFrame(),
                ok=False,
                error=f"unsupported tf {tf}",
            )

        gran = TF_OANDA[tf]
        # OANDA max 5000 candles per request
        count = min(limit, 5000)
        url = (
            f"{self.settings.oanda_base_url}/v3/instruments/"
            f"{remote_id}/candles"
        )
        params: dict[str, Any] = {
            "granularity": gran,
            "count": count,
            "price": "M",  # mid
        }
        try:
            self._throttle()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 401:
                    return CandlesResult(
                        symbol=remote_id,
                        tf=tf,
                        source=self.name,
                        df=pd.DataFrame(),
                        ok=False,
                        error="unauthorized (check OANDA_API_KEY)",
                    )
                if resp.status_code == 404:
                    return CandlesResult(
                        symbol=remote_id,
                        tf=tf,
                        source=self.name,
                        df=pd.DataFrame(),
                        ok=False,
                        error=f"instrument not found: {remote_id}",
                    )
                resp.raise_for_status()
                payload = resp.json()

            candles = payload.get("candles") or []
            rows = []
            for c in candles:
                if not c.get("complete", True):
                    # skip incomplete last candle for engine stability
                    continue
                mid = c.get("mid") or {}
                rows.append(
                    {
                        "ts": pd.Timestamp(c["time"], tz="UTC"),
                        "open": float(mid["o"]),
                        "high": float(mid["h"]),
                        "low": float(mid["l"]),
                        "close": float(mid["c"]),
                        "volume": float(c.get("volume") or 0),
                    }
                )
            if not rows:
                return CandlesResult(
                    symbol=remote_id,
                    tf=tf,
                    source=self.name,
                    df=pd.DataFrame(),
                    ok=False,
                    error="empty candles",
                )
            df = pd.DataFrame(rows).set_index("ts")
            df = normalize_ohlc(df)
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=df,
                ok=True,
                meta={"granularity": gran, "env": self.settings.oanda_env},
            )
        except Exception as e:
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=pd.DataFrame(),
                ok=False,
                error=str(e)[:300],
            )
