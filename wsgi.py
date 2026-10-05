"""
PythonAnywhere WSGI entry for OB Scanner v2 (FastAPI).

Free PA expects a WSGI callable named `application` — it does not run uvicorn.

Point the Web tab WSGI file at this path, e.g.:
  /home/skyhawk376/ob-scanner-v2/wsgi.py

v1 (old prototype) stays at /home/skyhawk376/ob-scanner — switch WSGI back there to restore it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"

# Data dirs under the project (writable on PA home)
os.environ.setdefault("CACHE_DIR", str(ROOT / "data" / "cache"))
os.environ.setdefault("RESULTS_DIR", str(ROOT / "data" / "results"))
os.environ.setdefault("TZ", "Europe/Paris")
# Ensure symbols.yaml is found via Settings defaults (ROOT in config = parents[3] from core/config.py)

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Create data dirs early
(ROOT / "data" / "cache").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "results" / "charts").mkdir(parents=True, exist_ok=True)

from a2wsgi import ASGIMiddleware  # noqa: E402

# Clear settings cache if previously imported (reload on PA)
try:
    from app.core.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass

from app.api.main import app as fastapi_app  # noqa: E402

application = ASGIMiddleware(fastapi_app)
