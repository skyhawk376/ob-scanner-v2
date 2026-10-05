#!/usr/bin/env python3
"""Refresh zone lifecycle from Parquet candles.

Usage:
  .venv/bin/python scripts/refresh_status.py --tf H1
  .venv/bin/python scripts/refresh_status.py --tf H1 --history   # backfill touches/reactions
  .venv/bin/python scripts/refresh_status.py --tf H1 --history --group FOREX,METAUX
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.monitor import compute_stats, refresh_statuses  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="OB lifecycle refresh")
    p.add_argument("--tf", default="H1")
    p.add_argument("--history", action="store_true", help="Re-detect mitigated + classify")
    p.add_argument("--group", default=None)
    p.add_argument("--min-score", type=int, default=4)
    p.add_argument("--no-notify", action="store_true")
    p.add_argument("--live-telegram", action="store_true", help="Send real Telegram if configured")
    args = p.parse_args()

    settings = get_settings()
    groups = [g.strip() for g in args.group.split(",")] if args.group else None
    print("=" * 64)
    print("OB lifecycle refresh", "HISTORY" if args.history else "LIVE")
    print("=" * 64)
    print(f"tf={args.tf}  db={settings.db_path}")
    print(f"telegram configured={settings.telegram_configured} dry_default={settings.telegram_dry_run}")

    summary = refresh_statuses(
        tf=args.tf,
        history=args.history,
        groups=groups,
        min_score=args.min_score,
        notify=not args.no_notify,
        force_dry_telegram=not args.live_telegram,
        settings=settings,
    )
    print(
        f"DONE {summary.elapsed_sec:.2f}s  zones={summary.n_zones} updated={summary.updated}  "
        f"notif={summary.notifications}"
    )
    print("By status:", summary.by_status)
    stats = compute_stats(tf=args.tf, settings=settings)
    print(
        f"Stats: touched={stats['n_touched']} reaction={stats['n_reaction']} "
        f"echec={stats['n_echec']} rate={stats['reaction_rate']}"
    )
    print("By group:", stats["by_group"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
