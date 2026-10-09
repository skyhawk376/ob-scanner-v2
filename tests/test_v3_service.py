"""v3 live layer: go-live guard, one message per event, BE/exit only after an entry,
ALERT_TFS gate, staleness, vanished zones, API + MCP + Telegram texts."""
from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.symbols import Instrument
from v3_fixtures import FLAT_AT, HAMMER, TOUCH, bull_h1, m15_for

TRADE = [TOUCH, HAMMER, FLAT_AT(101.0), (101.0, 101.7, 100.9, 101.6), (101.6, 102.9, 101.5, 102.8)] + [FLAT_AT(102.8)] * 10


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("TELEGRAM_DRY_RUN", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("ENABLE_FETCH", "false")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("ALERT_TFS", "M5,M15,M30,H1,H4,D,W")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.v3.service as svc
    import app.v3.detect as det

    inst = Instrument(id="XAUUSD", group="METAUX", primary="yfinance", yf="GC=F")
    monkeypatch.setattr(svc, "universe", lambda settings=None: [inst])
    real = det.detect_zones

    def detect4(*a, **k):  # fixture zone forced to 4★ (Tendance + Liquidité)
        return [{**z, "star_trend": True, "star_liquidity": True} for z in real(*a, **k)]

    monkeypatch.setattr(svc, "detect_zones", detect4)
    sent: list[str] = []
    import app.core.telegram as tg

    real_send = tg.send_telegram

    def spy(text, **kw):
        sent.append(text)
        return real_send(text, **kw)

    monkeypatch.setattr(tg, "send_telegram", spy)
    yield svc, get_settings(), sent
    get_settings.cache_clear()


def _write(settings, h1, m15, upto):
    from app.core.cache import write_cache

    write_cache(settings.cache_dir, "XAUUSD", "H1", h1[h1.index < upto])
    write_cache(settings.cache_dir, "XAUUSD", "M15", m15[m15.index < upto])


def _replay(svc, settings, h1, m15, start, minutes, step=15, tf="H1"):
    out = []
    for k in range(0, minutes + 1, step):
        now = start + pd.Timedelta(minutes=k)
        _write(settings, h1, m15, now)
        r = svc.refresh_tf(tf, settings=settings, now=now)
        out.append(r)
    return out


def test_full_lifecycle_messages_once_each(env):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    t_arm = h1.index[25]
    _replay(svc, settings, h1, m15, t_arm, 0)          # warm-up run arms H1 silently
    assert sent == []
    _replay(svc, settings, h1, m15, t_arm + pd.Timedelta(minutes=15), 6 * 60)
    kinds = [s.split("\n")[0] for s in sent]
    assert kinds[0].startswith("🟡 Zone touchée")
    assert kinds[1].startswith("🟢 ENTRÉE ACHAT")
    assert kinds[2].startswith("🔵") and "Passe ton SL au point d'entrée" in sent[2]
    assert kinds[3].startswith("✅ TP +2R")
    assert len(sent) == 4
    # re-run: no duplicate
    _replay(svc, settings, h1, m15, h1.index[-1], 0)
    assert len(sent) == 4
    st = svc.compute_stats(settings=settings)
    assert st["live"]["n"] == 1 and st["live"]["exits"] == {"tp": 1}
    assert st["live"]["avg_r"] < 2.0  # net of costs
    assert all("H4" not in s and "D1" not in s for s in sent)  # no trend line any more


def test_go_live_guard_no_old_alerts(env):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    end = h1.index[-1] + pd.Timedelta(hours=1)
    _replay(svc, settings, h1, m15, end, 0)            # first run after everything happened
    _replay(svc, settings, h1, m15, end + pd.Timedelta(minutes=15), 30)
    assert sent == []
    conn = __import__("app.v3.store", fromlist=["x"]).connect(settings.db_path)
    rows = conn.execute("SELECT event, status FROM v3_notify").fetchall()
    assert rows and all(r["status"].startswith("skipped") for r in rows)


def test_no_be_or_result_without_entry_alert(env):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    t_arm = h1.index[25]
    _replay(svc, settings, h1, m15, t_arm, 0)
    # scheduler down for 3h: entry becomes stale -> skipped -> BE/TP must stay silent
    late = h1.index[28] + pd.Timedelta(hours=3)
    _replay(svc, settings, h1, m15, late, 30)
    assert not any(s.startswith(("🟢", "🔵", "✅", "❌", "⚪")) for s in sent)


def test_alert_tfs_gate(env, monkeypatch):
    svc, settings, sent = env
    monkeypatch.setattr(type(settings), "tf_alerts_enabled", lambda self, tf: tf == "M5")
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[25] + pd.Timedelta(minutes=15), 6 * 60)
    assert sent == []


def test_low_score_zone_never_alerted(env, monkeypatch):
    svc, settings, sent = env
    import app.v3.detect as det

    monkeypatch.setattr(svc, "detect_zones", det.detect_zones)  # real stars: 2/5 on the fixture
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[25] + pd.Timedelta(minutes=15), 6 * 60)
    assert sent == []


def test_vanished_zone_still_tracked(env, monkeypatch):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[26], 15)          # zone stored (active, 4★)
    monkeypatch.setattr(svc, "detect_zones", lambda *a, **k: [])  # zone disappears from detection
    _replay(svc, settings, h1, m15, h1.index[28], 6 * 60)
    assert any(s.startswith("🟢 ENTRÉE") for s in sent)


def test_burst_cap(env, monkeypatch):
    svc, settings, sent = env
    import app.v3.params as P

    monkeypatch.setattr(P, "MAX_TOUCH_ALERTS_PER_CYCLE", 0)
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[25] + pd.Timedelta(minutes=15), 4 * 60)
    assert not any(s.startswith("🟡") for s in sent)


def test_track_open_other_tf(env):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[25] + pd.Timedelta(minutes=15), 4 * 60 - 15)
    n = len(sent)
    now = h1.index[28] + pd.Timedelta(minutes=75)
    _write(settings, h1, m15, h1.index[-1] + pd.Timedelta(hours=1))
    r = svc.track_open(settings=settings, now=h1.index[-1] + pd.Timedelta(hours=1))
    assert r["errors"] == [] and len(sent) >= n
    assert now  # smoke


def test_messages_render_french():
    from app.v3.alerts import sample_messages

    m = sample_messages()
    assert "Zone touchée" in m["touch"] and "★★★★☆" in m["touch"]
    assert "ENTRÉE ACHAT" in m["entry"] and "englobante M15" in m["entry"] and "TP (+2R)" in m["entry"]
    assert "Passe ton SL au point d'entrée" in m["be"]
    assert m["exit_tp"].startswith("✅ TP +2R") and m["exit_sl"].startswith("❌ SL") and m["exit_be_exit"].startswith("⚪")


# ---------------------------------------------------------------- API + MCP
@pytest.fixture()
def client(env):
    svc, settings, sent = env
    h1 = bull_h1()
    m15 = m15_for(h1, TRADE)
    _replay(svc, settings, h1, m15, h1.index[25], 0)
    _replay(svc, settings, h1, m15, h1.index[25] + pd.Timedelta(minutes=15), 6 * 60, step=60)
    from app.api.main import app

    with TestClient(app) as c:
        yield c


def test_api_zones_stats_strategy(client):
    z = client.get("/zones?tf=H1&statuses=tp,sl,be,en_position,touchee,invalidee").json()
    assert z["n"] == 1 and z["zones"][0]["status"] == "tp" and z["zones"][0]["trade_trigger"] == "marteau"
    assert set(z["zones"][0]["stars"]) == {"tendance", "liquidite", "vierge", "fibo", "session"}
    st = client.get("/stats").json()
    assert st["engine"] == "v3 Kasper" and st["live"]["n"] == 1
    s = client.get("/strategy").json()
    assert "NQ100" in s["groups"] and s["tp_r"] == 2.0 and s["time_stop"] is None
    h = client.get("/health").json()
    assert h["engine"] == "v3"
    assert client.get("/zones?tf=Daily").status_code == 200
    assert client.get("/zones?tf=XX").status_code == 400


def test_mcp_tools(client):
    from app.mcp import tools_impl as t

    lz = json.loads(t.tool_list_zones(tf="H1", status="tp"))
    assert lz["engine"] == "v3" and lz["n"] == 1
    zid = lz["zones"][0]["id"]
    gz = json.loads(t.tool_get_zone(zid))
    assert gz["id"] == zid and gz["result"]["trade"]["exit"] == "tp"
    gs = json.loads(t.tool_get_stats())
    assert gs["live"]["n"] == 1


def test_mcp_requires_token(tmp_path):
    """Fresh interpreter (asgi reads MCP_TOKEN at import): /mcp 401 without token, 200 with it."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    code = """
from fastapi.testclient import TestClient
from app.api.asgi import app
with TestClient(app, base_url="http://ob-scanner-v2.fly.dev") as c:
    a = c.post("/mcp", json={}).status_code
    b = c.post("/mcp", headers={"Authorization": "Bearer test-token", "Accept": "application/json, text/event-stream"},
               json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                     "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
    tools = c.post("/mcp", headers={"Authorization": "Bearer test-token", "Accept": "application/json, text/event-stream",
                   "mcp-session-id": b.headers.get("mcp-session-id", "")},
                   json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    print(a, b.status_code, "list_zones" in tools.text)
"""
    env = {**os.environ, "MCP_TOKEN": "test-token", "PYTHONPATH": str(root / "backend"),
           "RESULTS_DIR": str(tmp_path / "r"), "CACHE_DIR": str(tmp_path / "c"), "ENABLE_SCHEDULER": "false"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().splitlines()[-1] == "401 200 True", out.stderr[-2000:]
