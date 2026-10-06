"""Common provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Canonical TFs used by the scanner
TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D", "W")


@dataclass
class CandlesResult:
    symbol: str
    tf: str
    source: str
    df: pd.DataFrame
    ok: bool
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_bars(self) -> int:
        return 0 if self.df is None or self.df.empty else len(self.df)


class CandleProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(
        self,
        remote_id: str,
        tf: str,
        *,
        limit: int = 5000,
    ) -> CandlesResult:
        """Fetch OHLC for remote_id at timeframe tf. Returns CandlesResult."""

    def supports(self, tf: str) -> bool:
        return tf.upper() in TIMEFRAMES
