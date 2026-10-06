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


def test_format_zone_message_shows_tp_2r_not_distant_tp1(monkeypatch):
    """Telegram must show +2R target / RR 2.0 (REACTION_R=2.0), not liquidity TP1 with RR 32."""
    monkeypatch.setenv("REACTION_R", "2.0")
    from app.core.telegram import format_zone_message

    # bull: entry 100, sl 90 → risk 10 → TP(+2R)=120; distant tp1 at 420 → RR 32
    zone = {
        "id": "XAUUSD|H1|bull|t",
        "symbol": "XAUUSD",
        "tf": "H1",
        "direction": "bull",
        "score": 4,
        "low": 90.0,
        "high": 110.0,
        "entry": 100.0,
        "sl": 90.0,
        "tp1": 420.0,
        "rr_tp1": 32.0,
        "entry_mode": "mid",
    }
    msg = format_zone_message("new_zone", zone)
    assert "TP(+2R) 120" in msg
    assert "RR 2.0" in msg
    assert "+1R" not in msg and "RR 1.0" not in msg
    assert "420" not in msg
    assert "RR 32" not in msg
    assert "milieu OB" in msg

    # bear: entry 100, sl 110 → risk 10 → TP(+2R)=80
    zone_b = {
        **zone,
        "direction": "bear",
        "entry": 100.0,
        "sl": 110.0,
        "tp1": 10.0,
        "rr_tp1": 9.0,
        "entry_mode": "proximal",
    }
    msg_b = format_zone_message("reaction", zone_b)
    assert "Réaction +2R" in msg_b
    assert "TP(+2R) 80" in msg_b
    assert "RR 2.0" in msg_b
    assert "bas OB" in msg_b or "haut OB" in msg_b
