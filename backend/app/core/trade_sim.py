"""Realistic live trade outcome for a touched zone (Réaction tab / digest / /stats).

Same rules as scripts/rr2_optim_backtest.py sim_zone(entry='mid_live_fill',
hold=1, mgmt='none'):
  * the limit at zone["entry"] (mid) must actually be reached after the first
    touch, within FILL_CAP_H1 H1 bars → otherwise "non rempli" (not a trade);
  * from the fill: SL (-1R) / TP (+REACTION_R) / time stop 1h after the fill
    (R at the close after 1h);
  * M15 path when an M15 cache covers the touch, else H1 conservative:
    SL checked first (SL first if both hit in the same bar); on the fill bar the
    TP only counts if the CLOSE is beyond it (the bar's high may predate the fill);
    H1 time stop = close of the fill bar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

FILL_CAP_H1 = 24
HOLD_HOURS = 1.0

TRADE_PENDING = "pending"      # touched, limit not reached yet (still within cap)
TRADE_UNFILLED = "unfilled"    # « non rempli » — mid never reached within cap
TRADE_OPEN = "open"            # filled, hold window not finished
TRADE_CLOSED = "closed"        # tp | sl | time
TRADE_KEYS = (
    "trade_status", "trade_r", "trade_exit", "trade_fill_at", "trade_exit_at",
    "trade_model", "trade_tp", "trade_tp_r", "trade_ref",
)


def _utc(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()


def _ts(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _manage(o, h, l, c, k0: int, n_hold: int, entry: float, sl: float, bull: bool,
            tp_r: float) -> tuple[float | None, str, int]:
    """Walk n_hold bars from fill bar k0. Returns (R, exit, k_exit); R None if data ends."""
    risk = abs(entry - sl)
    sgn = 1.0 if bull else -1.0
    tp = entry + sgn * tp_r * risk
    n = len(c)
    for k in range(k0, k0 + n_hold):
        if k >= n:
            return None, "open", k
        adv = l[k] if bull else h[k]
        fav = h[k] if bull else l[k]
        if (adv <= sl) if bull else (adv >= sl):
            return -1.0, "sl", k
        ref = c[k] if k == k0 else fav
        if (ref >= tp) if bull else (ref <= tp):
            return float(tp_r), "tp", k
    k = k0 + n_hold - 1
    return float(sgn * (c[k] - entry) / risk), "time", k


def simulate_trade(
    h1: pd.DataFrame,
    zone: dict[str, Any],
    *,
    tp_r: float = 2.0,
    m15: pd.DataFrame | None = None,
    now: datetime | None = None,
    fill_cap_h1: int = FILL_CAP_H1,
    hold_hours: float = HOLD_HOURS,
) -> dict[str, Any]:
    """Return trade_* fields for a zone with touched_at. Never raises on bad data."""
    out: dict[str, Any] = {k: None for k in TRADE_KEYS}
    out["trade_tp_r"] = float(tp_r)
    touched_at = zone.get("touched_at")
    out["trade_ref"] = touched_at
    try:
        entry, sl = float(zone["entry"]), float(zone["sl"])
    except (KeyError, TypeError, ValueError):
        return out
    bull = zone.get("direction", "bull") == "bull"
    risk = abs(entry - sl)
    if not touched_at or risk <= 0 or h1 is None or h1.empty:
        return out
    out["trade_tp"] = entry + (1 if bull else -1) * tp_r * risk
    now_ts = _ts(now or datetime.now(timezone.utc))
    H = _utc(h1)
    # only bars that are fully closed at `now` are used for exits/fills
    H = H[H.index + pd.Timedelta(hours=1) <= now_ts]
    idx = H.index
    t_touch = _ts(touched_at)
    if len(idx) == 0 or t_touch < idx[0]:
        return out  # touch predates the candle cache → unknown (not counted)
    ti = int(idx.searchsorted(t_touch))
    if ti >= len(idx):
        out["trade_status"] = TRADE_PENDING
        return out
    o, h, l, c = (H[k].to_numpy(float) for k in ("open", "high", "low", "close"))

    # ---- M15 path (when it covers the touch) ----
    if m15 is not None and not m15.empty:
        M = _utc(m15)
        M = M[M.index + pd.Timedelta(minutes=15) <= now_ts]
        if len(M) and M.index[0] <= t_touch <= M.index[-1]:
            midx = M.index
            mo, mh, ml, mc = (M[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            s = int(midx.searchsorted(t_touch))
            cap_t = t_touch + pd.Timedelta(hours=fill_cap_h1 + 1)
            f = None
            for k in range(s, len(mc)):
                if midx[k] >= cap_t:
                    break
                if (ml[k] <= entry) if bull else (mh[k] >= entry):
                    f = k
                    break
            if f is not None:
                end_t = midx[f] + pd.Timedelta(hours=hold_hours)
                n_hold = max(int(midx.searchsorted(end_t)) - f, 1)
                r, why, ke = _manage(mo, mh, ml, mc, f, n_hold, entry, sl, bull, tp_r)
                out.update(trade_model="m15", trade_fill_at=midx[f].isoformat())
                if r is None:
                    out["trade_status"] = TRADE_OPEN
                    return out
                out.update(trade_status=TRADE_CLOSED, trade_r=round(r, 4), trade_exit=why,
                           trade_exit_at=(midx[ke] + pd.Timedelta(minutes=15)).isoformat())
                return out
            # M15 shows no fill: trust it only if it covers the whole cap window
            if midx[-1] + pd.Timedelta(minutes=15) >= cap_t:
                out.update(trade_status=TRADE_UNFILLED, trade_model="m15")
                return out

    # ---- H1 conservative ----
    f = None
    for k in range(ti, min(ti + fill_cap_h1 + 1, len(c))):
        if (l[k] <= entry) if bull else (h[k] >= entry):
            f = k
            break
    out["trade_model"] = "h1"
    if f is None:
        out["trade_status"] = TRADE_PENDING if (len(c) - ti) <= fill_cap_h1 else TRADE_UNFILLED
        return out
    n_hold = max(int(round(hold_hours)), 1)
    r, why, ke = _manage(o, h, l, c, f, n_hold, entry, sl, bull, tp_r)
    out["trade_fill_at"] = idx[f].isoformat()
    if r is None:
        out["trade_status"] = TRADE_OPEN
        return out
    out.update(trade_status=TRADE_CLOSED, trade_r=round(r, 4), trade_exit=why,
               trade_exit_at=(idx[ke] + pd.Timedelta(hours=1)).isoformat())
    return out


def trade_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """WR / avg R over closed trades (WR = R > 0)."""
    closed = [t for t in trades if t.get("trade_status") == TRADE_CLOSED and t.get("trade_r") is not None]
    rs = [float(t["trade_r"]) for t in closed]
    n = len(rs)
    exits: dict[str, int] = {}
    for t in closed:
        exits[t.get("trade_exit") or "?"] = exits.get(t.get("trade_exit") or "?", 0) + 1
    return {
        "n": n,
        "wins": sum(1 for r in rs if r > 0),
        "wr": (sum(1 for r in rs if r > 0) / n) if n else None,
        "avg_r": (sum(rs) / n) if n else None,
        "sum_r": round(sum(rs), 4),
        "exits": exits,
    }


def weekdays_between(a: pd.Timestamp, b: pd.Timestamp) -> float:
    """Approx. trading weekdays between two instants (≥ 1 when span > 0)."""
    days = (b - a).total_seconds() / 86400.0
    return max(days * 5.0 / 7.0, 0.0)

