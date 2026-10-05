#!/usr/bin/env python3
"""CLI: fetch OHLC for the watchlist, cache Parquet, print summary.

Usage (from repo root):
  .venv/bin/python scripts/fetch_candles.py
  .venv/bin/python scripts/fetch_candles.py --tf H1
  .venv/bin/python scripts/fetch_candles.py --tf H1,D --group FOREX,CRYPTO
  .venv/bin/python scripts/fetch_candles.py --symbols XAUUSD,EURUSD,BTC --tf H1
  .venv/bin/python scripts/fetch_candles.py --limit 300 --quiet
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.fetcher import fetch_all  # noqa: E402
from app.core.symbols import count_by_group, load_instruments  # noqa: E402
from app.providers.registry import ProviderHub  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OB scanner P0 — fetch candles")
    parser.add_argument(
        "--tf",
        default="H1",
        help="Comma-separated timeframes: H1,H4,D,W (default H1)",
    )
    parser.add_argument(
        "--group",
        default=None,
        help="Comma-separated groups: NQ100,METAUX,ENERGIE,FOREX,CRYPTO",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbol ids (overrides full list)",
    )
    parser.add_argument("--limit", type=int, default=800, help="Max bars per series")
    parser.add_argument("--no-cache", action="store_true", help="Do not write Parquet")
    parser.add_argument("--quiet", action="store_true", help="Less per-symbol output")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Exit non-zero if any symbol fails",
    )
    args = parser.parse_args()

    settings = get_settings()
    instruments = load_instruments(settings.symbols_yaml)
    hub = ProviderHub(settings)

    print("=" * 64)
    print("OB 5-star scanner — Phase 0 candle fetch")
    print("=" * 64)
    print(f"symbols.yaml : {settings.symbols_yaml}")
    print(f"instruments  : {len(instruments)}  {count_by_group(instruments)}")
    print(f"cache_dir    : {settings.cache_dir}")
    print(f"OANDA key    : {'SET' if hub.oanda.configured else 'MISSING (yfinance fallback for FX/metals/energy)'}")
    print(f"OANDA env    : {settings.oanda_env}  url={settings.oanda_base_url}")
    print(f"timezone     : {settings.tz}")
    print()

    tfs = [t.strip().upper() for t in args.tf.split(",") if t.strip()]
    groups = (
        [g.strip().upper() for g in args.group.split(",") if g.strip()]
        if args.group
        else None
    )
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else None
    )

    def on_item(item):
        if args.quiet:
            if item.ok:
                print(".", end="", flush=True)
            else:
                print("x", end="", flush=True)
            return
        status = "OK " if item.ok else "FAIL"
        extra = f"bars={item.n_bars}" if item.ok else f"err={item.error}"
        print(
            f"  [{status}] {item.symbol:10s} {item.tf:3s}  "
            f"{item.source:18s}  {extra}  ({item.elapsed_ms:.0f} ms)"
        )

    t0 = time.perf_counter()
    summary = fetch_all(
        tfs=tfs,
        groups=groups,
        symbols=symbols,
        settings=settings,
        limit=args.limit,
        write=not args.no_cache,
        on_item=on_item,
    )
    if args.quiet:
        print()

    print()
    print("-" * 64)
    print(
        f"DONE in {summary.elapsed_sec:.1f}s  "
        f"ok={summary.ok_count}  fail={summary.fail_count}  "
        f"series={len(summary.results)}  "
        f"symbols_ok={len(summary.unique_symbols_ok())}"
    )
    print("By source:")
    for src, st in sorted(summary.by_source().items()):
        print(f"  {src:16s}  ok={st['ok']:4d}  fail={st['fail']:4d}")

    fails = [r for r in summary.results if not r.ok]
    if fails:
        print()
        print(f"Failures ({len(fails)}):")
        for r in fails[:40]:
            print(f"  - {r.symbol} {r.tf} via {r.source}: {r.error}")
        if len(fails) > 40:
            print(f"  … +{len(fails) - 40} more")

    # parquet count
    n_parquet = len(list(settings.cache_dir.glob("*.parquet"))) if settings.cache_dir.exists() else 0
    print()
    print(f"Parquet files in cache: {n_parquet}")
    print(f"Wall clock: {time.perf_counter() - t0:.1f}s")

    if args.fail_fast and summary.fail_count:
        return 1
    # Success criterion: completes without crashing; partial OK is fine for P0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
