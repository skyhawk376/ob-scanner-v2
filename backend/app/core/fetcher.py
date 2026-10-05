"""Fetch OHLC for instruments, write Parquet cache, report stats."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..providers.base import CandlesResult
from ..providers.registry import ProviderHub
from ..core.cache import cache_path, merge_cache
from ..core.config import Settings, get_settings
from ..core.symbols import Instrument, load_instruments


@dataclass
class FetchItemResult:
    symbol: str
    group: str
    tf: str
    source: str
    ok: bool
    n_bars: int = 0
    error: str | None = None
    elapsed_ms: float = 0.0
    cache_path: str | None = None


@dataclass
class FetchSummary:
    results: list[FetchItemResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def elapsed_sec(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def by_source(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for r in self.results:
            key = (r.source or "unknown").split("/")[0]
            bucket = stats.setdefault(key, {"ok": 0, "fail": 0})
            if r.ok:
                bucket["ok"] += 1
            else:
                bucket["fail"] += 1
        return stats

    def unique_symbols_ok(self) -> set[str]:
        return {r.symbol for r in self.results if r.ok}


def fetch_instrument_tf(
    hub: ProviderHub,
    inst: Instrument,
    tf: str,
    *,
    settings: Settings,
    limit: int = 5000,
    write: bool = True,
) -> FetchItemResult:
    t0 = time.perf_counter()
    last_err: str | None = None
    last_source = inst.primary
    for pname in hub.provider_chain(inst):
        remote = hub.remote_id(inst, pname)
        if not remote:
            continue
        if pname == "oanda" and not hub.oanda.configured:
            last_err = "OANDA_API_KEY not set"
            last_source = "oanda"
            continue
        provider = hub.get(pname)
        result: CandlesResult = provider.fetch(remote, tf, limit=limit)
        last_source = result.source
        if result.ok and result.n_bars > 0:
            cpath = None
            if write:
                merged = merge_cache(settings.cache_dir, inst.id, tf, result.df)
                cpath = str(cache_path(settings.cache_dir, inst.id, tf))
                n_bars = len(merged)
            else:
                n_bars = result.n_bars
            return FetchItemResult(
                symbol=inst.id,
                group=inst.group,
                tf=tf,
                source=result.source,
                ok=True,
                n_bars=n_bars,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                cache_path=cpath,
            )
        last_err = result.error or "empty"
        last_source = result.source
    return FetchItemResult(
        symbol=inst.id,
        group=inst.group,
        tf=tf,
        source=last_source,
        ok=False,
        error=last_err or "all providers failed",
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


def fetch_all(
    *,
    tfs: Iterable[str] = ("H1",),
    groups: Iterable[str] | None = None,
    symbols: Iterable[str] | None = None,
    settings: Settings | None = None,
    limit: int = 1500,
    write: bool = True,
    on_item: Callable[[FetchItemResult], None] | None = None,
) -> FetchSummary:
    settings = settings or get_settings()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
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

    hub = ProviderHub(settings)
    summary = FetchSummary(started_at=time.time())
    tf_list = [t.upper() for t in tfs]

    for inst in filtered:
        for tf in tf_list:
            item = fetch_instrument_tf(
                hub, inst, tf, settings=settings, limit=limit, write=write
            )
            summary.results.append(item)
            if on_item:
                on_item(item)

    summary.finished_at = time.time()
    return summary
