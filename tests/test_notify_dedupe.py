"""Atomic claim_notify prevents duplicate Telegram reaction sends."""
from __future__ import annotations

import threading

from app.core.store import claim_notify, connect, was_notified


def test_claim_notify_only_once(tmp_path):
    db = tmp_path / "zones.sqlite"
    conn = connect(db)
    assert claim_notify(conn, "GBPAUD|H1|bull|t", "reaction") is True
    assert claim_notify(conn, "GBPAUD|H1|bull|t", "reaction") is False
    assert was_notified(conn, "GBPAUD|H1|bull|t", "reaction")
    # other events still claimable
    assert claim_notify(conn, "GBPAUD|H1|bull|t", "touchee") is True
    conn.close()


def test_claim_notify_concurrent(tmp_path):
    db = tmp_path / "zones.sqlite"
    connect(db).close()
    wins = []
    lock = threading.Lock()

    def worker():
        c = connect(db)
        ok = claim_notify(c, "Z|H1|bear|x", "reaction")
        with lock:
            wins.append(ok)
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sum(1 for w in wins if w) == 1
    assert sum(1 for w in wins if not w) == 7


def test_notify_zone_event_dedupe(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_DRY_RUN", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core import telegram as tg

    sends = []

    def fake_send(text, **kw):
        sends.append(text)
        return {"ok": True, "dry_run": True}

    monkeypatch.setattr(tg, "send_telegram", fake_send)
    zone = {
        "id": "GBPAUD|H1|bull|2026-10-05T10:00:00+00:00",
        "symbol": "GBPAUD",
        "tf": "H1",
        "direction": "bull",
        "score": 4,
        "low": 1.9,
        "high": 1.91,
        "entry": 1.905,
        "sl": 1.895,
        "tp1": 1.92,
        "rr_tp1": 1.5,
        "entry_mode": "mid",
    }
    r1 = tg.notify_zone_event("reaction", zone, force_dry=True)
    r2 = tg.notify_zone_event("reaction", zone, force_dry=True)
    r3 = tg.notify_zone_event("reaction", zone, force_dry=True)
    assert r1 and r1.get("ok") and not r1.get("skipped")
    assert r2 and r2.get("skipped") == "duplicate"
    assert r3 and r3.get("skipped") == "duplicate"
    assert len(sends) == 1
    get_settings.cache_clear()


def test_entry_mode_mid_from_env(monkeypatch):
    monkeypatch.setenv("ENTRY_MODE", "mid")
    from app.engine.params import entry_mode_from_env, params_for_tf, require_entry_fill_for_mode

    assert entry_mode_from_env() == "mid"
    assert params_for_tf("H1").entry_mode == "mid"
    assert require_entry_fill_for_mode() is False
