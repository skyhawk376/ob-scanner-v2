"""Engine parameters per timeframe (PLAN defaults)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineParams:
    pivot_n: int = 3
    atr_len: int = 14
    lookback: int = 500
    # displacement optional filter
    require_displacement: bool = False
    displacement_body_atr: float = 1.2
    # entry_mode: "proximal" = bull=OB high / bear=OB low (default);
    #             "mid" = legacy 50% mid if height > entry_mid_atr * ATR else open
    # (distal-edge entry bull=low / bear=high was reverted — R ≈ SL buffer only)
    entry_mode: str = "proximal"
    entry_mid_atr: float = 1.0  # used only when entry_mode == "mid"
    sl_buffer_atr: float = 0.05  # SL beyond distal edge
    # ★3 strict: entire zone on discount/premium side of 0.5
    fib_strict: bool = True
    # ★4
    liq_band_atr: float = 1.0
    liq_eq_atr: float = 0.1
    liq_eq_pct: float = 0.0005  # 0.05%
    # user locked: untaken pivot anywhere in the 1 ATR band fails ★4
    liq_pivot_band_atr: float = 1.0
    # ★1 eliminatory for display (still computed)
    require_fvg: bool = True
    # virgin: bars after OB+2 must not intersect zone
    # scoring
    min_score: int = 4
    require_fresh: bool = True
    # session windows in Europe/Paris wall clock (PLAN)
    # evaluated with ZoneInfo Europe/Paris
    london_start: tuple[int, int] = (8, 0)
    london_end: tuple[int, int] = (11, 30)
    ny_start: tuple[int, int] = (14, 30)
    ny_end: tuple[int, int] = (17, 30)
    # H4/D/W: ★5 pending until touch
    session_at_touch_tfs: tuple[str, ...] = ("H4", "D", "W")
    # Lifecycle reaction sensitivity (also overridable via env SOFT_REACTION_R / ENABLE_SOFT_REACTION)
    reaction_r: float = 1.0
    soft_reaction_r: float = 0.0  # 0 = soft OFF (default); set 0.5 when ENABLE_SOFT_REACTION=true


def entry_mode_from_env() -> str:
    """ENTRY_MODE env: proximal (default) | mid. Invalid → proximal."""
    raw = (os.environ.get("ENTRY_MODE") or "proximal").strip().lower()
    return raw if raw in ("proximal", "mid") else "proximal"


def require_entry_fill_for_mode(entry_mode: str | None = None) -> bool:
    """mid legacy: manage from first zone contact; proximal: wait limit fill at edge."""
    mode = (entry_mode or entry_mode_from_env()).strip().lower()
    return mode != "mid"


def params_for_tf(tf: str) -> EngineParams:
    tf = tf.upper()
    mode = entry_mode_from_env()
    if tf in ("H1",):
        return EngineParams(pivot_n=3, lookback=500, entry_mode=mode)
    if tf in ("H4",):
        return EngineParams(pivot_n=3, lookback=500, entry_mode=mode)
    if tf in ("D", "1D", "DAILY"):
        return EngineParams(pivot_n=2, lookback=400, entry_mode=mode)
    if tf in ("W", "1W", "WEEKLY"):
        return EngineParams(pivot_n=2, lookback=260, entry_mode=mode)
    return EngineParams(entry_mode=mode)
