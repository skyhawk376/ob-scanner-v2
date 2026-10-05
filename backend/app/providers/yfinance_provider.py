"""yfinance adapter — stocks, FX fallback, futures, remaining."""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

from ..core.cache import normalize_ohlc, resample_ohlc
from .base import CandleProvider, CandlesResult

# yfinance has no native 4h; we pull 1h and resample.
# period limits: 1h max ~730d; 1d/1wk many years.
TF_YF: dict[str, dict[str, Any]] = {
    "H1": {"interval": "1h", "period": "730d", "native": True},
    "H4": {"interval": "1h", "period": "730d", "native": False, "resample": "4h"},
    "D": {"interval": "1d", "period": "max", "native": True},
    "W": {"interval": "1wk", "period": "max", "native": True},
}


class YFinanceProvider(CandleProvider):
    name = "yfinance"

    def __init__(self, pause_sec: float = 0.35):
        self.pause_sec = pause_sec
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.pause_sec:
            time.sleep(self.pause_sec - elapsed)
        self._last_call = time.monotonic()

    def fetch(
        self,
        remote_id: str,
        tf: str,
        *,
        limit: int = 5000,
    ) -> CandlesResult:
        tf = tf.upper()
        if tf not in TF_YF:
            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=pd.DataFrame(),
                ok=False,
                error=f"unsupported tf {tf}",
            )
        cfg = TF_YF[tf]
        try:
            import yfinance as yf

            self._throttle()
            ticker = yf.Ticker(remote_id)
            raw = ticker.history(
                period=cfg["period"],
                interval=cfg["interval"],
                auto_adjust=True,
                actions=False,
            )
            if raw is None or raw.empty:
                # Retry once with download API (sometimes more reliable)
                self._throttle()
                raw = yf.download(
                    remote_id,
                    period=cfg["period"],
                    interval=cfg["interval"],
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )
            if raw is None or raw.empty:
                return CandlesResult(
                    symbol=remote_id,
                    tf=tf,
                    source=self.name,
                    df=pd.DataFrame(),
                    ok=False,
                    error="empty response",
                )

            # Flatten multiindex columns if present
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]

            rename = {
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            raw = raw.rename(columns=rename)
            keep = [c for c in ["open", "high", "low", "close", "volume"] if c in raw.columns]
            df = normalize_ohlc(raw[keep])

            if not cfg.get("native") and cfg.get("resample"):
                df = resample_ohlc(df, cfg["resample"])

            if limit and len(df) > limit:
                df = df.iloc[-limit:]

            return CandlesResult(
                symbol=remote_id,
                tf=tf,
                source=self.name,
                df=df,
                ok=True,
                meta={"interval": cfg["interval"], "resampled": not cfg.get("native", True)},
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
