"""Canonical timeframes for the live scanner (M5 … W) + parsing helpers.

Canonical ids (stored in DB / cache file names / API): M5, M15, M30, H1, H4, D, W.
Aliases accepted from env / API / UI: 5m, 15M, 30min, 1h, 4h, Daily, 1D, Weekly, 1W …
"""
from __future__ import annotations

ALL_TFS: tuple[str, ...] = ("M5", "M15", "M30", "H1", "H4", "D", "W")
INTRADAY_LOW_TFS: tuple[str, ...] = ("M5", "M15", "M30")

TF_MINUTES: dict[str, int] = {
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D": 1440,
    "W": 10080,
}

# Display/sort rank (higher TF first, like the old W/D/H4/H1 ranking)
TF_RANK: dict[str, int] = {"W": 0, "D": 1, "H4": 2, "H1": 3, "M30": 4, "M15": 5, "M5": 6}

# Pipeline processing order: H1 (Filtre B, Telegram) first so its latency never
# degrades, then the low TFs, then the slow HTFs.
TF_PRIORITY: tuple[str, ...] = ("H1", "M5", "M15", "M30", "H4", "D", "W")

_ALIASES: dict[str, str] = {
    "M5": "M5", "5M": "M5", "5MIN": "M5", "5": "M5",
    "M15": "M15", "15M": "M15", "15MIN": "M15", "15": "M15",
    "M30": "M30", "30M": "M30", "30MIN": "M30", "30": "M30",
    "H1": "H1", "1H": "H1", "60M": "H1", "60": "H1",
    "H4": "H4", "4H": "H4", "240": "H4",
    "D": "D", "D1": "D", "1D": "D", "DAILY": "D", "DAY": "D",
    "W": "W", "W1": "W", "1W": "W", "WEEKLY": "W", "WEEK": "W", "1WK": "W",
}


def normalize_tf(tf: str | None) -> str | None:
    """Canonical TF id or None when unknown/empty."""
    if tf is None:
        return None
    key = str(tf).strip().upper()
    if not key:
        return None
    return _ALIASES.get(key)


def parse_tf_list(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Comma list / iterable → canonical TFs (dedup, unknown dropped, input order kept)."""
    if raw is None:
        return []
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    out: list[str] = []
    for p in parts:
        t = normalize_tf(p)
        if t and t not in out:
            out.append(t)
    return out


def by_priority(tfs: list[str]) -> list[str]:
    """Order TFs for pipeline processing (H1 first)."""
    rank = {t: i for i, t in enumerate(TF_PRIORITY)}
    return sorted(dict.fromkeys(tfs), key=lambda t: rank.get(t, 99))


DEFAULT_SCHEDULE = "M5:5,M15:15,M30:30,H1:15,H4:60,D:120,W:360"


def parse_schedule(raw: str | None, tfs: list[str] | None = None) -> dict[str, int]:
    """`M5:5,M15:15,...` → {tf: minutes}. TFs missing from the schedule fall back to
    max(15, TF minutes) capped at 6h. Minimum cadence 5 min."""
    sched: dict[str, int] = {}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        t = normalize_tf(k)
        try:
            minutes = int(float(v.strip()))
        except ValueError:
            continue
        if t:
            sched[t] = max(5, minutes)
    for t in tfs or []:
        if t not in sched:
            sched[t] = max(15, min(TF_MINUTES.get(t, 60), 360))
    if tfs is not None:
        sched = {t: m for t, m in sched.items() if t in tfs}
    return sched
