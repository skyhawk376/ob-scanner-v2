"""H4 / D1 trend bias (close vs EMA50) — informational only, never filters alerts.

Same definition as scripts/momentum_filter_backtest.py (`ema50`):
    bias = sign(close - EMA50(close)) on the last CLOSED bar of the TF, needs
    >= 50 closed bars (warm-up) else None. A bar is "closed" at time T when
    bar_open + duration <= T. Stale series (last closed bar too old) → None.

Sources (cache only, no network at notify time):
    H4 : native H4 cache if present, else resampled from H1 (4h bins, epoch origin)
    D1 : native "D" cache (fetched a few times per day by the pipeline), else
         resampled from H1 (UTC days) — usually too short for EMA50 → None ("?").
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .cache import read_cache

EMA_SPAN = 50
STALE = {"H4": pd.Timedelta(days=4), "D1": pd.Timedelta(days=6)}
BIAS_KEYS = ("bias_h4", "bias_d1", "aligned_h4d1", "bias_at")


def _utc_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    kw = {"origin": "epoch"} if rule.endswith("h") else {}
    return (
        df.resample(rule, label="left", closed="left", **kw)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )


def _to_ts(T: Any) -> pd.Timestamp:
    if T is None:
        T = datetime.now(timezone.utc)
    t = pd.Timestamp(T)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def ema_bias_at(open_ts: pd.DatetimeIndex, close: np.ndarray, duration: pd.Timedelta,
                T: pd.Timestamp, stale: pd.Timedelta) -> int | None:
    """sign(close - EMA50) on the last bar closed at T (closed = open + duration <= T)."""
    if len(close) == 0:
        return None
    avail = open_ts + duration
    k = int(avail.searchsorted(T, side="right")) - 1
    if k < 0 or k < EMA_SPAN - 1:
        return None
    if (T - avail[k]) > stale:
        return None
    c = np.asarray(close[: k + 1], dtype=float)
    ema = pd.Series(c).ewm(span=EMA_SPAN, adjust=False).mean().to_numpy()[-1]
    return int(np.sign(c[-1] - ema))


def _daily_labels(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Map provider daily stamps (00:00 London = 23:00 UTC prev day, 00:00 NY = 04:00
    UTC, 00:00 UTC for crypto) to their calendar date (UTC midnight)."""
    return (idx + pd.Timedelta(hours=12)).floor("D")


def series_for(cache_dir: Path, symbol: str, h1: pd.DataFrame | None = None) -> dict:
    """{tf: (open_ts, close, duration, source)} for H4 and D1 when buildable."""
    out: dict[str, tuple] = {}
    if h1 is None:
        h1 = read_cache(cache_dir, symbol, "H1")
    h1 = _utc_index(h1) if h1 is not None and not h1.empty else None

    h4 = read_cache(cache_dir, symbol, "H4")
    if h4 is not None and not h4.empty:
        h4 = _utc_index(h4)
        out["H4"] = (h4.index, h4["close"].to_numpy(float), pd.Timedelta(hours=4), "H4")
    elif h1 is not None:
        r = _resample(h1[["open", "high", "low", "close"]], "4h")
        out["H4"] = (r.index, r["close"].to_numpy(float), pd.Timedelta(hours=4), "H1→4h")

    d = read_cache(cache_dir, symbol, "D")
    if d is not None and not d.empty:
        d = _utc_index(d)
        lab = _daily_labels(d.index)
        dd = pd.DataFrame({"close": d["close"].to_numpy(float)}, index=lab)
        dd = dd[~dd.index.duplicated(keep="last")]
        out["D1"] = (dd.index, dd["close"].to_numpy(float), pd.Timedelta(days=1), "D")
    elif h1 is not None:
        r = _resample(h1[["open", "high", "low", "close"]], "1D")
        out["D1"] = (r.index, r["close"].to_numpy(float), pd.Timedelta(days=1), "H1→1D")
    return out


def aligned_h4d1(direction: str, b_h4: int | None, b_d1: int | None) -> bool | None:
    """True = both aligned with the OB, False = at least one known TF against / flat,
    None = unknown (a TF missing and the known one(s) aligned)."""
    sgn = 1 if direction == "bull" else -1
    vals = [b_h4, b_d1]
    known = [v for v in vals if v is not None]
    if any(v != sgn for v in known):
        return False
    if len(known) < 2:
        return None
    return True


def compute_bias(
    symbol: str,
    direction: str,
    T: Any = None,
    *,
    cache_dir: Path,
    h1: pd.DataFrame | None = None,
    series: dict | None = None,
) -> dict[str, Any]:
    """Return {bias_h4, bias_d1, aligned_h4d1, bias_at}. Never raises."""
    t = _to_ts(T)
    res: dict[str, Any] = {"bias_h4": None, "bias_d1": None, "aligned_h4d1": None,
                           "bias_at": t.isoformat()}
    try:
        ser = series if series is not None else series_for(cache_dir, symbol, h1=h1)
        for tf, key in (("H4", "bias_h4"), ("D1", "bias_d1")):
            if tf in ser:
                idx, close, dur, _src = ser[tf]
                res[key] = ema_bias_at(idx, close, dur, t, STALE[tf])
    except Exception as e:  # never block an alert
        res["bias_error"] = str(e)[:200]
    res["aligned_h4d1"] = aligned_h4d1(direction, res["bias_h4"], res["bias_d1"])
    return res


def bias_at_for_zone(zone: dict[str, Any]) -> Any:
    """Bias reference time: first touch bar open (closed candles before it), else now."""
    return zone.get("touched_at") or None


def ensure_zone_bias(zone: dict[str, Any], *, cache_dir: Path, h1: pd.DataFrame | None = None,
                     force: bool = False, series: dict | None = None) -> dict[str, Any]:
    """Attach bias fields in place when missing or computed for another reference time."""
    T = bias_at_for_zone(zone)
    want = _to_ts(T).isoformat() if T else None
    have = zone.get("bias_at")
    if not force and have and "bias_h4" in zone and (want is None or have == want):
        return zone
    zone.update(compute_bias(str(zone.get("symbol")), str(zone.get("direction", "bull")), T,
                             cache_dir=cache_dir, h1=h1, series=series))
    return zone


def _emoji(v: int | None, direction: str) -> str:
    if v is None:
        return "?"
    return "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")


def bias_line(zone: dict[str, Any]) -> str:
    """`Tendance H4 🟢 / D1 🟢 → ✅ aligné H4+D1` (🟢 haussier, 🔴 baissier, ? inconnu)."""
    d = str(zone.get("direction", "bull"))
    h4, d1 = zone.get("bias_h4"), zone.get("bias_d1")
    al = zone.get("aligned_h4d1")
    if al is True:
        verdict = "✅ aligné H4+D1"
    elif al is False:
        verdict = "⚠️ contre-tendance"
    else:
        verdict = "❔ tendance incomplète"
    return f"· Tendance H4 {_emoji(h4, d)} / D1 {_emoji(d1, d)} → {verdict}"
