"""London / New York session windows in Europe/Paris."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def _in_window(t: time, start: tuple[int, int], end: tuple[int, int]) -> bool:
    s = time(start[0], start[1])
    e = time(end[0], end[1])
    return s <= t < e


def session_at(
    ts: datetime | pd_Timestamp,
    *,
    london_start: tuple[int, int] = (8, 0),
    london_end: tuple[int, int] = (11, 30),
    ny_start: tuple[int, int] = (14, 30),
    ny_end: tuple[int, int] = (17, 30),
) -> str | None:
    """Return 'London', 'NY', or None for a timestamp (any tz → Paris)."""
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    local = ts.astimezone(PARIS)
    t = local.timetz().replace(tzinfo=None)
    if _in_window(t, london_start, london_end):
        return "London"
    if _in_window(t, ny_start, ny_end):
        return "NY"
    return None


# avoid importing pandas at module level for type hint only
try:
    from pandas import Timestamp as pd_Timestamp
except ImportError:  # pragma: no cover
    pd_Timestamp = datetime  # type: ignore
