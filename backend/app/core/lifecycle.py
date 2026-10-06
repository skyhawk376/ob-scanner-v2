"""Zone lifecycle simulation from OHLC (Active → Touchée → Réaction/Échec/Expirée)."""
from __future__ import annotations

import os
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


def soft_reaction_r_from_env() -> float:
    """Soft reaction threshold in R. Default OFF (exit at +1R / opposing liquidity).

    Set ENABLE_SOFT_REACTION=true and SOFT_REACTION_R=0.5 to re-enable soft exit.
    """
    flag = os.environ.get("ENABLE_SOFT_REACTION", "false").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return 0.0
    raw = os.environ.get("SOFT_REACTION_R", "0.5").strip()
    try:
        v = float(raw)
    except ValueError:
        v = 0.5
    return max(0.0, v)


def count_tp1_from_env() -> bool:
    """Count opposing-liquidity tp1 as a reaction before +REACTION_R (legacy). Default OFF:
    with TP = +2R a nearer tp1 must not be reported as « Réaction +2R »."""
    return os.environ.get("REACTION_COUNT_TP1", "false").strip().lower() in ("1", "true", "yes", "on")


def reaction_r_from_env() -> float:
    """Primary reaction threshold in R (default 2.0 = TP +2R, live REACTION_R=2.0)."""
    raw = os.environ.get("REACTION_R", "2.0").strip()
    try:
        return max(0.01, float(raw))
    except ValueError:
        return 2.0


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
    reaction_threshold_r: float | None = None  # which R threshold fired

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
    soft_reaction_r: float | None = None,
    reaction_r: float | None = None,
    require_entry_fill: bool = True,
) -> LifecycleState:
    """Walk candles after OB to classify zone status (PLAN §7).

    Defaults (strategy):
    - soft reaction OFF (ENABLE_SOFT_REACTION=false) → exit at +1R / opposing liquidity
    - set ENABLE_SOFT_REACTION=true for soft 0.5R early exit
    - entry = mid (default) or proximal OB edge; SL beyond distal edge
    - Touchee = first zone contact; trade mgmt (MFE/SL/reaction) starts at entry fill
    - failure only on SL wick — NOT close alone beyond distal zone edge
    - touch/fill bar is evaluated for MFE / reaction (no skip)
    """
    state = LifecycleState()
    if df is None or df.empty:
        return state

    soft_r = soft_reaction_r_from_env() if soft_reaction_r is None else float(soft_reaction_r)
    primary_r = reaction_r_from_env() if reaction_r is None else float(reaction_r)
    # Effective reaction threshold = min of soft and primary when soft enabled
    thresholds = [primary_r]
    if soft_r > 0:
        thresholds.append(soft_r)
    react_threshold = min(thresholds)
    count_tp1 = count_tp1_from_env()

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
    filled = False
    touch_i: int | None = None

    for i in range(start, n):
        # expiry check while still active
        if not touched and (i - ob_i) > expiry_limit:
            state.status = STATUS_EXPIREE
            state.outcome = STATUS_EXPIREE
            state.expired_at = _ts_iso(index[i])
            state.events.append("expiree_bars")
            return state

        # distance expiry (zone mid vs close)
        mid = (zone_lo + zone_hi) / 2.0
        if not touched and atr > 0 and abs(mid - c[i]) / atr > MAX_DISTANCE_ATR:
            state.status = STATUS_EXPIREE
            state.outcome = STATUS_EXPIREE
            state.expired_at = _ts_iso(index[i])
            state.events.append("expiree_distance")
            return state

        intersects = l[i] <= zone_hi and h[i] >= zone_lo
        # Limit fill at entry: bull wick ≤ entry; bear wick ≥ entry
        if bull:
            hit_entry = l[i] <= entry
        else:
            hit_entry = h[i] >= entry

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
                # fall through — may fill + evaluate on same bar
            else:
                continue

        # --- post-touch: wait for entry fill before MFE / SL / reaction ---
        assert touch_i is not None
        if not filled:
            if not require_entry_fill or hit_entry:
                filled = True
                if require_entry_fill:
                    state.events.append("entry_fill")
                # fall through — evaluate MFE / reaction / SL on fill bar
            else:
                continue
        if bull:
            fav = (h[i] - entry) / risk
            adv = (entry - l[i]) / risk
            state.mfe_r = max(state.mfe_r, fav)
            state.mae_r = max(state.mae_r, adv)
            # Failure: SL only (wick through SL). Close beyond distal edge alone is NOT échec.
            if l[i] <= sl:
                state.status = STATUS_ECHEC
                state.outcome = STATUS_ECHEC
                state.failed_at = _ts_iso(index[i])
                state.events.append("echec")
                return state
            tp1 = zone.get("tp1")
            hit_r = h[i] >= entry + react_threshold * risk
            hit_tp = count_tp1 and tp1 is not None and h[i] >= float(tp1)
            if hit_r or hit_tp:
                state.status = STATUS_REACTION
                state.outcome = STATUS_REACTION
                state.reacted_at = _ts_iso(index[i])
                state.reaction_threshold_r = react_threshold
                state.events.append("reaction" if react_threshold >= primary_r else "reaction_soft")
                return state
        else:
            fav = (entry - l[i]) / risk
            adv = (h[i] - entry) / risk
            state.mfe_r = max(state.mfe_r, fav)
            state.mae_r = max(state.mae_r, adv)
            if h[i] >= sl:
                state.status = STATUS_ECHEC
                state.outcome = STATUS_ECHEC
                state.failed_at = _ts_iso(index[i])
                state.events.append("echec")
                return state
            tp1 = zone.get("tp1")
            hit_r = l[i] <= entry - react_threshold * risk
            hit_tp = count_tp1 and tp1 is not None and l[i] <= float(tp1)
            if hit_r or hit_tp:
                state.status = STATUS_REACTION
                state.outcome = STATUS_REACTION
                state.reacted_at = _ts_iso(index[i])
                state.reaction_threshold_r = react_threshold
                state.events.append("reaction" if react_threshold >= primary_r else "reaction_soft")
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
    if life.reaction_threshold_r is not None:
        out["reaction_threshold_r"] = life.reaction_threshold_r
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
