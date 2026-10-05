#!/usr/bin/env bash
# Cron helper for PythonAnywhere free (ENABLE_SCHEDULER=false).
# Typical schedule (PA Tasks or external cron that SSHs in):
#   H1 every ~1–2h weekday: refresh without history
#   Daily once: --history for Touches/Réaction backfill
#
# On free PA, live Yahoo/Binance fetch often fails (whitelist). Preferred flow:
#   1) On your machine: python scripts/fetch_candles.py --tf H1 --quiet
#   2) Upload/rsync data/cache/ → ~/ob-scanner-v2/data/cache/
#   3) Run this script on PA for lifecycle only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
export ENABLE_SCHEDULER=false
export TZ=Europe/Paris

TF="${1:-H1}"
MODE="${2:-refresh}"  # refresh | history

if [[ "$MODE" == "history" ]]; then
  python scripts/refresh_status.py --tf "$TF" --history --no-notify
else
  python scripts/refresh_status.py --tf "$TF" --no-notify
fi
