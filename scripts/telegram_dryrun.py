#!/usr/bin/env python3
"""Write sample Telegram messages to data/results/telegram_dryrun.log

Usage:
  .venv/bin/python scripts/telegram_dryrun.py
  .venv/bin/python scripts/telegram_dryrun.py --digest
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.store import connect, list_zones  # noqa: E402
from app.core.telegram import (  # noqa: E402
    format_zone_message,
    notify_zone_event,
    run_digest,
    send_telegram,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--digest", action="store_true")
    p.add_argument("--limit", type=int, default=8)
    args = p.parse_args()

    settings = get_settings()
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    log = settings.telegram_log_path
    print(f"Dry-run log → {log}")
    print(f"TELEGRAM configured={settings.telegram_configured}")

    send_telegram("OB Scanner — dry-run ping", settings=settings, force_dry=True)

    conn = connect(settings.db_path)
    try:
        zones = list_zones(conn, min_score=4, limit=500)
    finally:
        conn.close()

    # Prefer lifecycle-interesting zones
    preferred = [
        z
        for z in zones
        if z.get("status") in ("touchee", "reaction", "echec")
    ] or zones

    n = 0
    for z in preferred[: args.limit]:
        st = z.get("status") or "active"
        events = ["new_zone"]
        if st in ("touchee", "reaction", "echec"):
            events.append("touchee")
        if st == "reaction":
            events.append("reaction")
        if st == "echec":
            events.append("echec")
        for ev in events:
            # bypass PLAN filters for demo samples by writing formatted message directly
            # while also exercising notify for touchee/reaction when session allows
            msg = format_zone_message(ev, z)
            send_telegram(msg, settings=settings, force_dry=True)
            n += 1
            # also try deduped notify path
            notify_zone_event(ev, z, settings=settings, force_dry=True, dedupe=True)

    if args.digest or True:
        run_digest(settings=settings, force_dry=True, label="07:45 pré-Londres")
        run_digest(settings=settings, force_dry=True, label="14:15 pré-NY")

    print(f"Wrote ~{n}+ digests lines to {log}")
    if log.exists():
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        print(f"Log lines total: {len(lines)}")
        for line in lines[-3:]:
            print(" ", line[:160], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
