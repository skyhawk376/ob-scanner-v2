import copy
import json
from datetime import date, datetime
from pathlib import Path

from app.aerogest import state
from app.aerogest.parse import Slot, format_alert, is_b23, parse_aircraft_planning, parse_fleet
from app.aerogest.service import run_once
from app.aerogest.telegram import find_start_chat

FIX = Path(__file__).parent / "fixtures"
DAILY = json.loads((FIX / "aerogest_daily.json").read_text())
ACFT = json.loads((FIX / "aerogest_aircraft.json").read_text())
NOW = datetime(2026, 10, 12, 9, 0)


def test_fleet_and_b23():
    fleet = parse_fleet(DAILY)
    assert [a.reg for a in fleet if is_b23(a.type)] == ["F-HMLR", "F-HRIV", "F-HRSJ"]
    assert not is_b23("DR400/160") and is_b23("b 23")


def test_parse_free_slots_day():
    days = parse_aircraft_planning("F-HRIV", ACFT, 30, False, datetime(2026, 10, 12, 0, 0))
    d = days[date(2026, 10, 12)]
    # aero day 07:51–19:54 minus bookings 12:00–13:30, 14:00–16:00
    assert [(s.start, s.end) for s in d] == [(471, 720), (810, 840), (960, 1194)]


def test_past_time_excluded_and_min_duration():
    d = parse_aircraft_planning("F-HRIV", ACFT, 60, False, datetime(2026, 10, 12, 11, 0))[date(2026, 10, 12)]
    assert [(s.start, s.end) for s in d] == [(660, 720), (960, 1194)]


def test_civil_night_option():
    d = parse_aircraft_planning("F-HRIV", ACFT, 30, True, datetime(2026, 10, 12))[date(2026, 10, 12)]
    assert d[0].start == 501 and d[-1].end == 1164


def test_format_alert():
    msg = format_alert(Slot("F-HRIV", date(2026, 12, 24), 840, 960))
    assert msg == ("✈️ Créneau libre — F-HRIV (B23)\nJeudi 24/12 · 14:00–16:00\n"
                   "https://online.aerogest.fr/Schedule/planning/daily/20261224")


def test_diff_new_only_and_dedupe(tmp_path):
    conn = state.connect(tmp_path / "db.sqlite")
    d = date(2026, 10, 12)
    assert state.apply_snapshot(conn, "F-HRIV", {d: [Slot("F-HRIV", d, 600, 720)]}) == []  # silent new day
    # slight shrink / small extension (<30 min) → nothing
    assert state.apply_snapshot(conn, "F-HRIV", {d: [Slot("F-HRIV", d, 600, 735)]}) == []
    # cancellation frees 13:00–15:00 next to it → one alert
    new = state.apply_snapshot(conn, "F-HRIV", {d: [Slot("F-HRIV", d, 600, 900)]})
    assert [(s.start, s.end) for s in new] == [(600, 900)]
    state.mark_alerted(conn, new[0])
    # same state again → nothing
    assert state.apply_snapshot(conn, "F-HRIV", {d: [Slot("F-HRIV", d, 600, 900)]}) == []


class FakeClient:
    logged_in = True

    def __init__(self, acft):
        self.acft = acft
        self.calls = 0

    def daily(self, day):
        return DAILY

    def aircraft(self, acft_id, start):
        self.calls += 1
        return self.acft if start == date(2026, 10, 12) else {"lignes": []}


CFG = {"enabled": True, "user": "u", "password": "p", "token": "T", "chat_id": "", "min_minutes": 30,
       "horizon_days": 60, "exclude_civil_night": False, "hours": "7-22"}


def test_run_silent_first_then_alert_on_cancellation(tmp_path):
    db = tmp_path / "db.sqlite"
    sent = []
    sender = lambda tok, chat, text: sent.append((chat, text)) or True
    r = run_once(db, NOW, FakeClient(ACFT), CFG, sender, discover=lambda t: "42")
    assert r["ok"] and r["first_run"] and r["new_count"] == 0 and r["free_count"] > 0
    assert len(sent) == 1 and sent[0][1].startswith("✅ Surveillance Aérogest B23 activée")
    # cancel F-HRIV 14:00–16:00 on 12/10
    acft2 = copy.deepcopy(ACFT)
    acft2["lignes"][0]["sublignes"][0]["reservations"] = [
        r for r in acft2["lignes"][0]["sublignes"][0]["reservations"] if r["debut"] != "202610121400"]
    r = run_once(db, NOW, FakeClient(acft2), CFG, sender, discover=lambda t: "42")
    alerts = [t for _, t in sent[1:]]
    assert r["new_count"] == 3  # same fixture served for each B23 → one alert per aircraft
    assert "F-HRIV (B23)\nLundi 12/10 · 13:30–19:54" in alerts[1] or any("F-HRIV" in a and "13:30–19:54" in a for a in alerts)
    # no repeat
    r = run_once(db, NOW, FakeClient(acft2), CFG, sender, discover=lambda t: "42")
    assert r["new_count"] == 0 and len(sent) == 4


def test_chat_unknown_sends_nothing(tmp_path):
    sent = []
    r = run_once(tmp_path / "d.sqlite", NOW, FakeClient(ACFT), CFG, lambda *a: sent.append(a) or True,
                 discover=lambda t: None)
    assert r["ok"] and not r["chat_known"] and sent == []


def test_errors_are_contained(tmp_path):
    class Boom(FakeClient):
        def daily(self, day):
            raise RuntimeError("down")
    r = run_once(tmp_path / "d.sqlite", NOW, Boom(ACFT), CFG, lambda *a: True, discover=lambda t: None)
    assert r == {"ok": False, "error": "RuntimeError: down"}


def test_outside_hours_skipped(tmp_path):
    assert run_once(tmp_path / "d.sqlite", datetime(2026, 10, 12, 23, 0), FakeClient(ACFT), CFG)["skipped"]


def test_find_start_chat():
    ups = [{"message": {"chat": {"id": -5, "type": "group"}, "text": "/start"}},
           {"message": {"chat": {"id": 7, "type": "private"}, "text": "hello"}},
           {"message": {"chat": {"id": 9, "type": "private"}, "text": "/start"}}]
    assert find_start_chat(ups) == "9" and find_start_chat([]) is None
