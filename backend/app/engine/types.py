"""Zone dataclass and helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Zone:
    id: str
    symbol: str
    tf: str
    direction: str  # "bull" | "bear"
    ob_index: int
    bos_index: int
    leg_index: int
    ts_ob: str  # ISO UTC
    ts_bos: str
    low: float
    high: float
    open: float
    close: float
    # stars
    star1_fvg: bool
    star2_trend: bool
    star3_fib: bool
    star4_liquidity: bool
    star5_session: bool
    star5_pending: bool  # True on H4/D/W until touch-time eval
    score: int
    fresh: bool
    trend: str  # "bull" | "bear" | "range"
    # levels
    entry: float
    sl: float
    tp1: float | None
    tp2: float
    rr_tp1: float | None
    rr_tp2: float
    atr: float
    fib_eq: float
    swing_low: float
    swing_high: float
    distance_atr: float  # |mid - last_close| / ATR
    last_close: float
    session_label: str | None = None  # "London" | "NY" | None
    sweep: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
