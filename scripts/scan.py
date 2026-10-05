#!/usr/bin/env python3
"""CLI: scan cached Parquet for OB 5-star zones.

Usage:
  .venv/bin/python scripts/scan.py --tf H1
  .venv/bin/python scripts/scan.py --tf H1 --group METAUX,FOREX
  .venv/bin/python scripts/scan.py --tf H1 --symbols XAUUSD,EURUSD --min-score 3
  .venv/bin/python scripts/scan.py --tf H1 --no-persist
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.scanner import run_scan  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="OB 5-star scanner — Phase 1")
    p.add_argument("--tf", default="H1", help="Comma-separated: H1,H4,D,W")
    p.add_argument("--group", default=None, help="NQ100,METAUX,ENERGIE,FOREX,CRYPTO")
    p.add_argument("--symbols", default=None, help="Comma-separated ids")
    p.add_argument("--min-score", type=int, default=4)
    p.add_argument("--include-mitigated", action="store_true", help="Do not require fresh")
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--top", type=int, default=15, help="Print top N zones")
    args = p.parse_args()

    settings = get_settings()
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

    print("=" * 64)
    print("OB 5-star scanner — Phase 1 scan")
    print("=" * 64)
    print(f"cache_dir  : {settings.cache_dir}")
    print(f"tfs        : {tfs}")
    print(f"min_score  : {args.min_score}")
    print(f"fresh only : {not args.include_mitigated}")
    print()

    def on_sym(meta):
        if args.quiet:
            ch = "." if meta.ok and meta.n_zones == 0 else ("*" if meta.n_zones else "x")
            if not meta.ok:
                ch = "x"
            elif meta.n_zones:
                ch = str(min(meta.n_zones, 9))
            else:
                ch = "."
            print(ch, end="", flush=True)
            return
        status = "OK " if meta.ok else "FAIL"
        extra = f"zones={meta.n_zones} bars={meta.n_bars}" if meta.ok else f"err={meta.error}"
        if meta.n_zones or not meta.ok:
            print(f"  [{status}] {meta.symbol:10s} {meta.tf:3s}  {extra}  ({meta.elapsed_ms:.0f} ms)")

    summary = run_scan(
        tfs=tfs,
        groups=groups,
        symbols=symbols,
        settings=settings,
        min_score=args.min_score,
        require_fresh=not args.include_mitigated,
        persist=not args.no_persist,
        on_symbol=on_sym,
    )
    if args.quiet:
        print()

    ok_sym = sum(1 for s in summary.per_symbol if s.ok)
    fail_sym = sum(1 for s in summary.per_symbol if not s.ok)
    with_z = sum(1 for s in summary.per_symbol if s.n_zones > 0)
    by_score = Counter(z.score for z in summary.zones)
    by_dir = Counter(z.direction for z in summary.zones)
    by_group = Counter()
    # map symbol→group from per_symbol
    sym_group = {s.symbol: s.group for s in summary.per_symbol}
    for z in summary.zones:
        by_group[sym_group.get(z.symbol, "?")] += 1

    print()
    print("-" * 64)
    print(
        f"DONE in {summary.elapsed_sec:.2f}s  "
        f"symbols_ok={ok_sym} fail={fail_sym} with_zones={with_z}  "
        f"zones={len(summary.zones)}"
    )
    print(f"By score : {dict(sorted(by_score.items(), reverse=True))}")
    print(f"By dir   : {dict(by_dir)}")
    print(f"By group : {dict(by_group)}")
    if summary.db_path:
        print(f"SQLite   : {summary.db_path}")
    if summary.json_path:
        print(f"JSON     : {summary.json_path}")

    # XAUUSD highlight (fresh from this run; if none, re-scan mitigated for context)
    xau = [z for z in summary.zones if z.symbol == "XAUUSD"]
    print()
    print(f"XAUUSD fresh zones (score>={args.min_score}): {len(xau)}")
    if not xau and (symbols is None or "XAUUSD" in (symbols or []) or groups is None or (groups and "METAUX" in groups)):
        from app.core.scanner import scan_symbol
        from app.core.symbols import load_instruments
        insts = [i for i in load_instruments(settings.symbols_yaml) if i.id == "XAUUSD"]
        if insts:
            mz, _ = scan_symbol(
                insts[0], tfs[0], settings=settings,
                min_score=args.min_score, require_fresh=False,
            )
            mz = [z for z in mz if z.score >= args.min_score]
            print(f"XAUUSD mitigated (for reference): {len(mz)}")
            for z in mz[:5]:
                stars = "".join(
                    "★" if s else "☆"
                    for s in (z.star1_fvg, z.star2_trend, z.star3_fib, z.star4_liquidity, z.star5_session)
                )
                print(
                    f"  [mitigated] {z.direction:4s} score={z.score} {stars}  "
                    f"zone=[{z.low:.4g},{z.high:.4g}] entry={z.entry:.4g} SL={z.sl:.4g}  "
                    f"ob={z.ts_ob} dist={z.distance_atr:.2f}ATR"
                )
    label = "XAUUSD samples" if xau else f"Top {min(args.top, len(summary.zones))}"
    print(f"--- {label} ---")
    for z in (xau[: args.top] if xau else summary.zones[: args.top]):
        stars = "".join(
            "★" if s else "☆"
            for s in (
                z.star1_fvg,
                z.star2_trend,
                z.star3_fib,
                z.star4_liquidity,
                z.star5_session,
            )
        )
        pend = " (★5 pending)" if z.star5_pending else ""
        sess = f" {z.session_label}" if z.session_label else ""
        print(
            f"  {z.symbol:8s} {z.tf:3s} {z.direction:4s}  score={z.score} {stars}{pend}{sess}  "
            f"zone=[{z.low:.4g},{z.high:.4g}]  entry={z.entry:.4g} SL={z.sl:.4g}  "
            f"TP1={z.tp1 if z.tp1 is None else round(z.tp1, 4)} RR1={None if z.rr_tp1 is None else round(z.rr_tp1, 2)}  "
            f"dist={z.distance_atr:.2f}ATR  ob={z.ts_ob}"
        )

    if not summary.zones and fail_sym == len(summary.per_symbol):
        print("\nNo cache found — run scripts/fetch_candles.py first.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
