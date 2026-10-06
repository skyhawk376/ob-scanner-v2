"""Scan pipeline: Parquet → detect → filter → store."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..engine.detect import detect_zones
from ..engine.params import EngineParams, params_for_tf
from ..engine.types import Zone
from .cache import read_cache
from .config import Settings, get_settings
from .store import connect, dump_json, list_zones, record_run, upsert_zones
from .symbols import Instrument, load_instruments


@dataclass
class ScanSymbolResult:
    symbol: str
    group: str
    tf: str
    n_bars: int
    n_zones: int
    ok: bool
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class ScanSummary:
    zones: list[Zone] = field(default_factory=list)
    per_symbol: list[ScanSymbolResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    db_path: str | None = None
    json_path: str | None = None

    @property
    def elapsed_sec(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


def scan_symbol(
    inst: Instrument,
    tf: str,
    *,
    settings: Settings,
    params: EngineParams | None = None,
    min_score: int = 4,
    require_fresh: bool = True,
) -> tuple[list[Zone], ScanSymbolResult]:
    t0 = time.perf_counter()
    df = read_cache(settings.cache_dir, inst.id, tf)
    if df is None or df.empty:
        return [], ScanSymbolResult(
            symbol=inst.id,
            group=inst.group,
            tf=tf,
            n_bars=0,
            n_zones=0,
            ok=False,
            error="no cache",
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
    try:
        zones = detect_zones(
            df,
            symbol=inst.id,
            tf=tf,
            params=params or params_for_tf(tf),
            min_score=min_score,
            require_fresh=require_fresh,
        )
        return zones, ScanSymbolResult(
            symbol=inst.id,
            group=inst.group,
            tf=tf,
            n_bars=len(df),
            n_zones=len(zones),
            ok=True,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        return [], ScanSymbolResult(
            symbol=inst.id,
            group=inst.group,
            tf=tf,
            n_bars=len(df),
            n_zones=0,
            ok=False,
            error=str(e)[:300],
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )


def run_scan(
    *,
    tfs: Iterable[str] = ("H1",),
    groups: Iterable[str] | None = None,
    symbols: Iterable[str] | None = None,
    settings: Settings | None = None,
    min_score: int = 4,
    require_fresh: bool = True,
    persist: bool = True,
    on_symbol: Callable[[ScanSymbolResult], None] | None = None,
) -> ScanSummary:
    settings = settings or get_settings()
    instruments = load_instruments(settings.symbols_yaml)
    group_set = {g.upper() for g in groups} if groups else None
    symbol_set = {s.upper() for s in symbols} if symbols else None

    filtered: list[Instrument] = []
    for inst in instruments:
        if group_set and inst.group.upper() not in group_set:
            continue
        if symbol_set and inst.id.upper() not in symbol_set:
            continue
        filtered.append(inst)

    # XAUUSD first
    filtered.sort(key=lambda i: (0 if i.id == "XAUUSD" else 1, i.id))

    summary = ScanSummary(started_at=time.time())
    all_zones: list[Zone] = []
    tf_list = [t.upper() for t in tfs]

    for tf in tf_list:
        params = params_for_tf(tf)
        for inst in filtered:
            zones, meta = scan_symbol(
                inst,
                tf,
                settings=settings,
                params=params,
                min_score=min_score,
                require_fresh=require_fresh,
            )
            summary.per_symbol.append(meta)
            all_zones.extend(zones)
            if on_symbol:
                on_symbol(meta)

    # Global sort with XAUUSD pin
    tf_rank = {"W": 0, "D": 1, "H4": 2, "H1": 3, "M30": 4, "M15": 5, "M5": 6}
    all_zones.sort(
        key=lambda z: (
            0 if z.symbol == "XAUUSD" else 1,
            -z.score,
            -int(z.star3_fib),
            tf_rank.get(z.tf, 9),
            z.distance_atr,
        )
    )
    summary.zones = all_zones
    summary.finished_at = time.time()

    if persist:
        results_dir = Path(settings.cache_dir).parent / "results"
        db_path = results_dir / "zones.sqlite"
        json_path = results_dir / f"zones_{'-'.join(tf_list)}.json"
        conn = connect(db_path)
        try:
            for tf in tf_list:
                z_tf = [z for z in all_zones if z.tf == tf]
                syms = {i.id for i in filtered}
                upsert_zones(conn, z_tf, tf=tf, symbols=syms, preserve_lifecycle=True)
            record_run(
                conn,
                tf=",".join(tf_list),
                n_symbols=len(filtered) * len(tf_list),
                n_zones=len(all_zones),
                elapsed_sec=summary.elapsed_sec,
                meta={"min_score": min_score, "require_fresh": require_fresh},
            )
        finally:
            conn.close()
        dump_json(
            json_path,
            all_zones,
            meta={
                "tfs": tf_list,
                "n_zones": len(all_zones),
                "elapsed_sec": summary.elapsed_sec,
                "min_score": min_score,
            },
        )
        summary.db_path = str(db_path)
        summary.json_path = str(json_path)

    return summary


def load_stored_zones(
    *,
    tf: str | None = None,
    min_score: int = 4,
    symbol: str | None = None,
    group: str | None = None,
    status: str | None = None,
    statuses: list[str] | None = None,
    settings: Settings | None = None,
    limit: int = 500,
    active_only: bool = False,
) -> list[dict]:
    settings = settings or get_settings()
    db_path = Path(settings.results_dir) / "zones.sqlite" if hasattr(settings, "results_dir") else Path(settings.cache_dir).parent / "results" / "zones.sqlite"
    if not db_path.exists():
        return []
    # Filtre B: clamp groups + min stars (STRATEGY_LOCK). None = no group filter.
    gl = settings.clamp_groups(group) if group or settings.strategy_lock else None
    min_score = settings.clamp_min_score(min_score)
    group_symbols = None
    if gl is not None:
        if not gl:
            return []
        instruments = load_instruments(settings.symbols_yaml)
        gset = set(gl)
        group_symbols = {i.id for i in instruments if i.group.upper() in gset}
    conn = connect(db_path)
    try:
        return list_zones(
            conn,
            tf=tf,
            group_symbols=group_symbols,
            min_score=min_score,
            symbol=symbol,
            status=status,
            statuses=statuses,
            limit=limit,
            active_only_for_scanner=active_only,
        )
    finally:
        conn.close()
