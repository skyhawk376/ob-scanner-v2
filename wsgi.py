"""
PythonAnywhere WSGI entry for OB Scanner v2 (FastAPI via a2wsgi).

Point the Web tab WSGI file at this path, or keep a thin /var/www/..._wsgi.py
that only imports `application` from here.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"

os.environ.setdefault("CACHE_DIR", str(ROOT / "data" / "cache"))
os.environ.setdefault("RESULTS_DIR", str(ROOT / "data" / "results"))
os.environ.setdefault("TZ", "Europe/Paris")
# Scheduler off on PA free (background threads + WSGI = flaky)
os.environ.setdefault("ENABLE_SCHEDULER", "false")

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

(ROOT / "data" / "cache").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results" / "charts").mkdir(parents=True, exist_ok=True)

# PA WSGI workers have no running loop; create one before a2wsgi uses it.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from a2wsgi import ASGIMiddleware  # noqa: E402

try:
    from app.core.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass

from app.api.main import app as fastapi_app  # noqa: E402

# wait_time: avoid hanging forever after response if ASGI cleanup stalls
application = ASGIMiddleware(fastapi_app, wait_time=30.0)
