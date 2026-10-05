"""Zone lifecycle simulation from OHLC (Active → Touchée → Réaction/Échec/Expirée)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..engine.sessions import session_at

STATUS_ACTIVE = "active"
STATUS_TOUCHEE = "touchee"
STATUS_REACTION = "reaction"
STATUS_ECHEC = "echec"
STATUS_EXPIREE = "expiree"

EXPIRY_BARS = {"H1": 200, "H4": 150, "D": 120, "W": 52}
MAX_DISTANCE_ATR = 8.0


@dataclass
class LifecycleState:
    status: str = STATUS_ACTIVE
    touched_at: str | None = None
    touched_session: str | None = None
    star5_at_touch: bool | None = None
    reacted_at: str | None = None
    failed_at: str | None = None
    expired_at: str | None = None
    outcome: str | None = None  # reaction | echec | expiree | None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    bars_since_ob: int = 0
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ts_iso(ts) -> str:
    if hasattr(ts, "isoformat"):
        t = ts
        if getattr(t, "tzinfo", None) is None:
            t = t.tz_localize("UTC") if hasattr(t, "tz_localize") else t
        return t.isoformat()
    return str(ts)


def _find_ob_index(index: pd.DatetimeIndex, ts_ob: str) -> int:
    target = pd.Timestamp(ts_ob)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    else:
        target = target.tz_convert("UTC")
    # exact or nearest at/after
    for i, ts in enumerate(index):
        t = ts if ts.tzinfo else ts.tz_localize("UTC")
        if t >= target:
            return i
    return -1


def simulate_lifecycle(
    df: pd.DataFrame,
    zone: dict[str, Any],
    *,
    now: datetime | None = None,
) -> LifecycleState:
    """Walk candles after OB to classify zone status (PLAN §7)."""
    state = LifecycleState()
    if df is None or df.empty:
        return state

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        return state
    if work.index.tz is None:
        work.index = work.index.tz_localize("UTC")
    else:
        work.index = work.index.tz_convert("UTC")

    o = work["open"].to_numpy(float)
    h = work["high"].to_numpy(float)
    l = work["low"].to_numpy(float)
    c = work["close"].to_numpy(float)
    n = len(work)
    index = work.index

    ob_i = _find_ob_index(index, zone["ts_ob"])
    if ob_i < 0:
        return state

    zone_lo = float(zone["low"])
    zone_hi = float(zone["high"])
    entry = float(zone["entry"])
    sl = float(zone["sl"])
    atr = float(zone.get("atr") or 0.0) or max(zone_hi - zone_lo, 1e-9)
    direction = zone.get("direction", "bull")
    bull = direction == "bull"
    risk = abs(entry - sl)
    if risk <= 0:
        risk = 0.05 * atr

    tf = str(zone.get("tf", "H1")).upper()
    expiry_limit = EXPIRY_BARS.get(tf, 200)
    start = min(ob_i + 3, n)  # after OB+2
    state.bars_since_ob = max(0, n - 1 - ob_i)

    touched = False
    touch_i: int | None = None

    for i in range(start, n):
        # expiry check while still active
        if not touched and (i - ob_i) > expiry_limit:
            state.status = STATUS_EXPIREE
            state.outcome = STATUS_EXPIREE
            state.expired_at = _ts_iso(index[i])
            state.events.append("expiree_bars")
            return state

        # distance expiry (mid vs close)
        mid = (zone_lo + zone_hi) / 2.0
        if not touched and atr > 0 and abs(mid - c[i]) / atr > MAX_DISTANCE_ATR:
            state.status = STATUS_EXPIREE
            state.outcome = STATUS_EXPIREE
            state.expired_at = _ts_iso(index[i])
            state.events.append("expiree_distance")
            return state

        intersects = l[i] <= zone_hi and h[i] >= zone_lo

        if not touched:
            if intersects:
                touched = True
                touch_i = i
                state.status = STATUS_TOUCHEE
                state.touched_at = _ts_iso(index[i])
                sess = session_at(index[i])
                state.touched_session = sess
                state.star5_at_touch = sess is not None
                state.events.append("touchee")
            continue

        # --- post-touch ---
        assert touch_i is not None
        if bull:
            # MFE / MAE in R
            fav = (h[i] - entry) / risk
            adv = (entry - l[i]) / risk
            state.mfe_r = max(state.mfe_r, fav)
            state.mae_r = max(state.mae_r, adv)
            # SL / distal failure: close below SL or wick through SL
            if l[i] <= sl or c[i] < zone_lo:
                state.status = STATUS_ECHEC
                state.outcome = STATUS_ECHEC
                state.failed_at = _ts_iso(index[i])
                state.events.append("echec")
                return state
            # Réaction: +1R or TP1 without failure
            tp1 = zone.get("tp1")
            hit_1r = h[i] >= entry + risk
            hit_tp = tp1 is not None and h[i] >= float(tp1)
            if hit_1r or hit_tp:
                state.status = STATUS_REACTION
                state.outcome = STATUS_REACTION
                state.reacted_at = _ts_iso(index[i])
                state.events.append("reaction")
                return state
        else:
            fav = (entry - l[i]) / risk
            adv = (h[i] - entry) / risk
            state.mfe_r = max(state.mfe_r, fav)
            state.mae_r = max(state.mae_r, adv)
            if h[i] >= sl or c[i] > zone_hi:
                state.status = STATUS_ECHEC
                state.outcome = STATUS_ECHEC
                state.failed_at = _ts_iso(index[i])
                state.events.append("echec")
                return state
            tp1 = zone.get("tp1")
            hit_1r = l[i] <= entry - risk
            hit_tp = tp1 is not None and l[i] <= float(tp1)
            if hit_1r or hit_tp:
                state.status = STATUS_REACTION
                state.outcome = STATUS_REACTION
                state.reacted_at = _ts_iso(index[i])
                state.events.append("reaction")
                return state

    # end of series
    if not touched:
        if state.bars_since_ob > expiry_limit:
            state.status = STATUS_EXPIREE
            state.outcome = STATUS_EXPIREE
            state.expired_at = _ts_iso(index[-1])
            state.events.append("expiree_bars")
        else:
            state.status = STATUS_ACTIVE
    else:
        # still in zone / waiting for reaction
        state.status = STATUS_TOUCHEE
    return state


def merge_lifecycle_into_payload(zone: dict[str, Any], life: LifecycleState) -> dict[str, Any]:
    out = dict(zone)
    out["status"] = life.status
    out["touched_at"] = life.touched_at
    out["touched_session"] = life.touched_session
    out["star5_at_touch"] = life.star5_at_touch
    out["reacted_at"] = life.reacted_at
    out["failed_at"] = life.failed_at
    out["expired_at"] = life.expired_at
    out["outcome"] = life.outcome
    out["mfe_r"] = round(life.mfe_r, 3)
    out["mae_r"] = round(life.mae_r, 3)
    out["bars_since_ob"] = life.bars_since_ob
    # resolve pending ★5 at touch
    if life.star5_at_touch and out.get("star5_pending"):
        out["star5_session"] = True
        out["star5_pending"] = False
        out["score"] = (
            int(out.get("star1_fvg"))
            + int(out.get("star2_trend"))
            + int(out.get("star3_fib"))
            + int(out.get("star4_liquidity"))
            + 1
        )
        out["session_label"] = life.touched_session
    return out
