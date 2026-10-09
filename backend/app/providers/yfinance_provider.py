"""yfinance adapter — stocks, FX fallback, futures, remaining."""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

from ..core.cache import normalize_ohlc, resample_ohlc
from .base import CandleProvider, CandlesResult

# yfinance has no native 4h; we pull 1h and resample.
# Yahoo limits: 5m/15m/30m only the last 60 days; 1h ~730d; 1d/1wk many years.
# Intraday downloads are sized from `limit` (see _period_for) instead of always
# pulling the max range: same bars after the `limit` slice, ~10x fewer bytes.
TF_YF: dict[str, dict[str, Any]] = {
    # 1m: Yahoo serves only the last ~7 days (v3 trigger for M5 zones)
    "M1": {"interval": "1m", "period": "5d", "native": True, "bar_min": 1, "max_days": 6, "min_days": 1},
    "M5": {"interval": "5m", "period": "59d", "native": True, "bar_min": 5, "max_days": 59},
    "M15": {"interval": "15m", "period": "59d", "native": True, "bar_min": 15, "max_days": 59},
    "M30": {"interval": "30m", "period": "59d", "native": True, "bar_min": 30, "max_days": 59},
    "H1": {"interval": "1h", "period": "730d", "native": True, "bar_min": 60, "max_days": 729,
           "min_days": 60},
    "H4": {"interval": "1h", "period": "730d", "native": False, "resample": "4h",
           "bar_min": 240, "max_days": 729, "min_days": 60},
    "D": {"interval": "1d", "period": "max", "native": True},
    "W": {"interval": "1wk", "period": "max", "native": True},
}


def _period_for(cfg: dict[str, Any], limit: int | None) -> str:
    """Yahoo `period` covering ~`limit` bars of the TF (weekends/closed hours ×1.6 + 3d)."""
    bar_min = cfg.get("bar_min")
    if not bar_min or not limit:
        return cfg["period"]
    days = int(limit * bar_min / 1440.0 * 1.6) + 3
    days = max(days, int(cfg.get("min_days", 5)))
    days = min(days, int(cfg.get("max_days", 59)))
    return f"{days}d"


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
            period = _period_for(cfg, limit)
            ticker = yf.Ticker(remote_id)
            raw = ticker.history(
                period=period,
                interval=cfg["interval"],
                auto_adjust=True,
                actions=False,
            )
            if raw is None or raw.empty:
                # Retry once with download API (sometimes more reliable)
                self._throttle()
                raw = yf.download(
                    remote_id,
                    period=period,
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
                meta={"interval": cfg["interval"], "period": period, "resampled": not cfg.get("native", True)},
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
