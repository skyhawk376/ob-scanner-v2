"""Refresh zone lifecycle from Parquet candles + optional history backfill."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..engine.detect import detect_zones
from ..engine.params import params_for_tf, require_entry_fill_for_mode
from .cache import read_cache
from .config import Settings, get_settings
from .lifecycle import (
    STATUS_ACTIVE,
    STATUS_ECHEC,
    STATUS_EXPIREE,
    STATUS_REACTION,
    STATUS_TOUCHEE,
    merge_lifecycle_into_payload,
    simulate_lifecycle,
)
from .store import connect, list_zones, replace_zones, update_zone_lifecycle
from .symbols import load_instruments
from .telegram import notify_zone_event
from .trade_sim import (
    TRADE_CLOSED,
    TRADE_OPEN,
    TRADE_PENDING,
    TRADE_UNFILLED,
    simulate_trade,
    trade_summary,
    weekdays_between,
)
from .trend_bias import ensure_zone_bias, series_for

_TOUCHED = (STATUS_TOUCHEE, STATUS_REACTION, STATUS_ECHEC)


class _Enricher:
    """Per-run memo of H4/D1/M15 series so bias + trade sim stay cheap."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._series: dict[str, dict] = {}
        self._m15: dict[str, Any] = {}

    def series(self, symbol: str, h1) -> dict:
        if symbol not in self._series:
            self._series[symbol] = series_for(self.settings.cache_dir, symbol, h1=h1)
        return self._series[symbol]

    def m15(self, symbol: str):
        if symbol not in self._m15:
            df = read_cache(self.settings.cache_dir, symbol, "M15")
            self._m15[symbol] = None if df is None or df.empty else df
        return self._m15[symbol]

    def __call__(self, zone: dict[str, Any], h1) -> dict[str, Any]:
        """Bias at touch (H4/D1, closed bars) + realistic trade outcome. Never raises."""
        if not zone.get("touched_at") or zone.get("status") not in _TOUCHED:
            return zone
        sym = str(zone.get("symbol"))
        try:
            ensure_zone_bias(zone, cache_dir=self.settings.cache_dir, h1=h1,
                             series=self.series(sym, h1))
        except Exception as e:  # pragma: no cover - never block lifecycle
            zone["bias_error"] = str(e)[:200]
        try:
            from .lifecycle import reaction_r_from_env

            tp_r = reaction_r_from_env()
            final = zone.get("trade_status") in (TRADE_CLOSED, TRADE_UNFILLED)
            same = (
                zone.get("trade_ref") == zone.get("touched_at")
                and float(zone.get("trade_tp_r") or 0) == float(tp_r)
            )
            if not (final and same):
                zone.update(simulate_trade(h1, zone, tp_r=tp_r, m15=self.m15(sym)))
        except Exception as e:  # pragma: no cover
            zone["trade_error"] = str(e)[:200]
        return zone


@dataclass
class RefreshSummary:
    updated: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    notifications: int = 0
    elapsed_sec: float = 0.0
    n_zones: int = 0
    mode: str = "refresh"


def _group_map(settings: Settings) -> dict[str, str]:
    return {i.id: i.group for i in load_instruments(settings.symbols_yaml)}


def refresh_statuses(
    *,
    tf: str = "H1",
    settings: Settings | None = None,
    notify: bool = True,
    force_dry_telegram: bool | None = True,
    history: bool = False,
    min_score: int = 4,
    groups: Iterable[str] | None = None,
    symbols: Iterable[str] | None = None,
) -> RefreshSummary:
    """Update lifecycle for stored zones, or backfill from history detection.

    history=True: re-detect with require_fresh=False then simulate (for Touches/Réaction stats).
    """
    settings = settings or get_settings()
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    summary = RefreshSummary(mode="history" if history else "refresh")
    gmap = _group_map(settings)
    group_set = {g.upper() for g in groups} if groups else None
    symbol_set = {s.upper() for s in symbols} if symbols else None

    enrich = _Enricher(settings)
    conn = connect(settings.db_path)
    try:
        if history:
            # Detect all score>=min including mitigated, then lifecycle
            instruments = load_instruments(settings.symbols_yaml)
            payloads: list[dict[str, Any]] = []
            for inst in instruments:
                if group_set and inst.group.upper() not in group_set:
                    continue
                if symbol_set and inst.id.upper() not in symbol_set:
                    continue
                df = read_cache(settings.cache_dir, inst.id, tf)
                if df is None or df.empty:
                    continue
                zones = detect_zones(
                    df,
                    symbol=inst.id,
                    tf=tf,
                    params=params_for_tf(tf),
                    min_score=min_score,
                    require_fresh=False,
                    require_fvg=True,
                )
                for z in zones:
                    d = z.to_dict()
                    prev_status = None
                    life = simulate_lifecycle(
                        df, d, require_entry_fill=require_entry_fill_for_mode()
                    )
                    merged = merge_lifecycle_into_payload(d, life)
                    enrich(merged, df)
                    payloads.append(merged)
                    summary.transitions.append(
                        {
                            "id": merged["id"],
                            "symbol": merged["symbol"],
                            "from": prev_status,
                            "to": life.status,
                        }
                    )
                    if notify:
                        # emit synthetic events for final state (deduped)
                        if life.status in (STATUS_TOUCHEE, STATUS_REACTION, STATUS_ECHEC):
                            # first touch
                            n = notify_zone_event(
                                "touchee",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
                        if life.status == STATUS_REACTION:
                            n = notify_zone_event(
                                "reaction",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
                        if life.status == STATUS_ECHEC:
                            n = notify_zone_event(
                                "echec",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
                        # new zone alerts (PLAN filter inside)
                        n = notify_zone_event(
                            "new_zone",
                            merged,
                            settings=settings,
                            force_dry=force_dry_telegram,
                        )
                        if n and not n.get("skipped"):
                            summary.notifications += 1

            syms = {p["symbol"] for p in payloads}
            replace_zones(conn, payloads, tf=tf.upper(), symbols=syms)
            summary.updated = len(payloads)
            summary.n_zones = len(payloads)
            summary.by_status = dict(Counter(p.get("status", "active") for p in payloads))
        else:
            # Refresh existing DB rows
            zones = list_zones(conn, tf=tf, min_score=1, limit=5000)
            filtered = []
            for z in zones:
                if group_set and gmap.get(z["symbol"], "").upper() not in group_set:
                    continue
                if symbol_set and z["symbol"].upper() not in symbol_set:
                    continue
                filtered.append(z)

            for z in filtered:
                df = read_cache(settings.cache_dir, z["symbol"], z.get("tf") or tf)
                if df is None or df.empty:
                    continue
                prev = z.get("status") or STATUS_ACTIVE
                life = simulate_lifecycle(
                    df, z, require_entry_fill=require_entry_fill_for_mode()
                )
                merged = merge_lifecycle_into_payload(z, life)
                enrich(merged, df)
                update_zone_lifecycle(conn, merged)
                # Commit per zone so a crash mid-loop cannot re-fire transitions
                conn.commit()
                summary.updated += 1
                if life.status != prev:
                    summary.transitions.append(
                        {
                            "id": merged["id"],
                            "symbol": merged["symbol"],
                            "from": prev,
                            "to": life.status,
                        }
                    )
                    if notify:
                        if life.status == STATUS_TOUCHEE and prev == STATUS_ACTIVE:
                            n = notify_zone_event(
                                "touchee",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
                        # Only notify reaction when entering from active/touchee
                        if life.status == STATUS_REACTION and prev in (
                            STATUS_ACTIVE,
                            STATUS_TOUCHEE,
                        ):
                            n = notify_zone_event(
                                "reaction",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
                        if life.status == STATUS_ECHEC and prev in (
                            STATUS_ACTIVE,
                            STATUS_TOUCHEE,
                        ):
                            n = notify_zone_event(
                                "echec",
                                merged,
                                settings=settings,
                                force_dry=force_dry_telegram,
                            )
                            if n and not n.get("skipped"):
                                summary.notifications += 1
            summary.n_zones = len(filtered)
            from .store import count_by_status

            summary.by_status = count_by_status(conn, tf=tf)
    finally:
        conn.close()

    summary.elapsed_sec = time.time() - t0
    return summary


def _parse_ts(s: str | None):
    """Parse ISO-ish timestamps from zone lifecycle fields; return aware/naive datetime or None."""
    if not s:
        return None
    try:
        from datetime import datetime

        raw = str(s).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _closed_span_and_rate(decided: list[dict]) -> tuple[float | None, float | None]:
    """Span (days) from first to last closed trade; trades/day = n_closed / span."""
    stamps = []
    for z in decided:
        ts = _parse_ts(z.get("reacted_at") or z.get("failed_at") or z.get("touched_at"))
        if ts is not None:
            stamps.append(ts)
    if len(stamps) < 2:
        # Single (or zero) closed trade: rate undefined; span None
        return (None, None)
    delta = (max(stamps) - min(stamps)).total_seconds() / 86400.0
    if delta <= 0:
        return (None, None)
    return (delta, len(decided) / delta)


def realistic_stats(
    zones: list[dict[str, Any]],
    *,
    gmap: dict[str, str] | None = None,
    now=None,
    since=None,
) -> dict[str, Any]:
    """Realistic live stats: a trade exists only once price reached the mid entry
    after the touch; outcome TP(+REACTION_R) / SL(-1R) / time stop 1h after fill.

    Unfilled touches = « non rempli » (excluded from WR). Splits by H4+D1 alignment.
    """
    import pandas as pd

    from .lifecycle import reaction_r_from_env

    gmap = gmap or {}
    now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    touched = [z for z in zones if z.get("touched_at") and (z.get("status") in _TOUCHED)]
    if since is not None:
        s_ts = pd.Timestamp(since)
        s_ts = s_ts.tz_localize("UTC") if s_ts.tzinfo is None else s_ts
        touched = [z for z in touched if _ts_ge(z.get("touched_at"), s_ts)]
    counts = Counter(z.get("trade_status") or "unknown" for z in touched)
    closed = [z for z in touched if z.get("trade_status") == TRADE_CLOSED]

    def split(pred) -> dict[str, Any]:
        return trade_summary([z for z in closed if pred(z)])

    first = None
    for z in touched:
        t = _parse_ts(z.get("touched_at"))
        if t is not None:
            t = pd.Timestamp(t)
            t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
            first = t if first is None or t < first else first
    if since is not None:
        first = s_ts if first is None else min(first, s_ts)
    wd = weekdays_between(first, now_ts) if first is not None else 0.0
    overall = trade_summary(closed)
    al = split(lambda z: z.get("aligned_h4d1") is True)
    nal = split(lambda z: z.get("aligned_h4d1") is not True)
    by_group: dict[str, Any] = {}
    for g in sorted({gmap.get(z.get("symbol", ""), "?") for z in closed}):
        by_group[g] = split(lambda z, g=g: gmap.get(z.get("symbol", ""), "?") == g)
    return {
        "method": "fill au mid après touch · TP +%gR / SL -1R / time stop 1h après fill · "
        "M15 si dispo sinon H1 conservateur (SL d'abord)" % reaction_r_from_env(),
        "tp_r": reaction_r_from_env(),
        "n_touched": len(touched),
        "n_closed": overall["n"],
        "n_unfilled": counts.get(TRADE_UNFILLED, 0),
        "n_pending": counts.get(TRADE_PENDING, 0),
        "n_open": counts.get(TRADE_OPEN, 0),
        "n_unknown": counts.get("unknown", 0),
        "fill_rate": (
            overall["n"] / (overall["n"] + counts.get(TRADE_UNFILLED, 0))
            if (overall["n"] + counts.get(TRADE_UNFILLED, 0))
            else None
        ),
        "wr": overall["wr"],
        "avg_r": overall["avg_r"],
        "sum_r": overall["sum_r"],
        "exits": overall["exits"],
        "weekdays": round(wd, 2),
        "trades_per_day": (overall["n"] / wd) if wd >= 1 else None,
        "aligned": {**al, "trades_per_day": (al["n"] / wd) if wd >= 1 else None},
        "not_aligned": {**nal, "trades_per_day": (nal["n"] / wd) if wd >= 1 else None},
        "n_aligned_unknown": sum(1 for z in closed if z.get("aligned_h4d1") is None),
        "by_group": by_group,
        "models": dict(Counter(z.get("trade_model") or "?" for z in closed)),
    }


def _ts_ge(s: str | None, ref) -> bool:
    import pandas as pd

    t = _parse_ts(s)
    if t is None:
        return False
    t = pd.Timestamp(t)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t >= ref


def compute_stats(
    *,
    tf: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    conn = connect(settings.db_path)
    try:
        zones = list_zones(conn, tf=tf, min_score=1, limit=10000)
    finally:
        conn.close()

    gmap = _group_map(settings)
    # Filtre B: stats only over the live universe (4★+, METAUX/FOREX/CRYPTO)
    zones = [z for z in zones if settings.zone_in_strategy(gmap.get(z.get("symbol", "")), z.get("score"))]
    by_status = Counter(z.get("status") or "active" for z in zones)
    touched = [z for z in zones if z.get("status") in (STATUS_TOUCHEE, STATUS_REACTION, STATUS_ECHEC)]
    reacted = [z for z in zones if z.get("status") == STATUS_REACTION]
    failed = [z for z in zones if z.get("status") == STATUS_ECHEC]
    decided = reacted + failed
    reaction_rate = (len(reacted) / len(decided)) if decided else None

    def bucket(key_fn, *, touched_only: bool = False):
        """N = touched count when touched_only (stats denominators for Réaction tab)."""
        c: Counter = Counter()
        r: Counter = Counter()
        f: Counter = Counter()
        tch: Counter = Counter()
        for z in zones:
            k = key_fn(z)
            st = z.get("status") or "active"
            is_touched = st in (STATUS_TOUCHEE, STATUS_REACTION, STATUS_ECHEC)
            if touched_only and not is_touched:
                continue
            c[k] += 1
            if is_touched:
                tch[k] += 1
            if st == STATUS_REACTION:
                r[k] += 1
            if st == STATUS_ECHEC:
                f[k] += 1
        out = {}
        for k in sorted(c.keys()):
            dec = r[k] + f[k]
            n_base = tch[k] if touched_only else c[k]
            out[k] = {
                "n": n_base,
                "n_all": c[k],
                "touched": tch[k],
                "reaction": r[k],
                "echec": f[k],
                "reaction_rate": (r[k] / dec) if dec else None,
                "reaction_rate_touched": (r[k] / tch[k]) if tch[k] else None,
            }
        return out

    decided_n = len(decided)
    # Trades fermés = réactions + échecs (décidés). Optional trades/day over closed span.
    span_days, trades_per_day = _closed_span_and_rate(decided)

    return {
        "n": len(zones),
        "by_status": dict(by_status),
        "n_touched": len(touched),
        "n_reaction": len(reacted),
        "n_echec": len(failed),
        "n_decided": decided_n,
        "n_closed": decided_n,  # alias UI: « Trades fermés »
        "reaction_rate": reaction_rate,
        "reaction_rate_touched": (len(reacted) / len(touched)) if touched else None,
        "denominator": "decided (réaction+échec = trades fermés)",
        "span_days": span_days,
        "trades_per_day": trades_per_day,
        "by_tf": bucket(lambda z: z.get("tf") or "?", touched_only=True),
        "by_score": bucket(lambda z: str(z.get("score") or "?"), touched_only=True),
        "by_group": bucket(lambda z: gmap.get(z.get("symbol", ""), "?"), touched_only=True),
        # Session at touch only — use touched_session (same as TouchesTab)
        "by_session": bucket(lambda z: z.get("touched_session") or "—", touched_only=True),
        # Realistic trades (fill at mid required, TP +REACTION_R / SL / time stop 1h).
        "realistic": realistic_stats(zones, gmap=gmap),
        "realistic_7d": realistic_stats(
            zones, gmap=gmap, since=datetime.now(timezone.utc) - timedelta(days=7)
        ),
        "legacy_note": "reaction_rate = ancienne méthode (géré dès le 1er contact, sans time stop)",
    }
