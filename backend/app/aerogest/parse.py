"""Pure parsing of Aérogest planning JSON (api/schedule/bookingapi/*)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Legend colours (planning tooltip). Background bands that make the aircraft unbookable.
COLOR_UNAVAILABLE = "#f4e1ff"  # Indisponibilité
COLOR_AERO_NIGHT = "#11719c"   # Nuit aéronautique
COLOR_CIVIL_NIGHT = "#39c2ff"  # Nuit civile (bookable VFR-day margin, kept by default)


@dataclass(frozen=True)
class Aircraft:
    id: int
    reg: str
    type: str


@dataclass(frozen=True)
class Slot:
    reg: str
    day: date
    start: int  # minutes since local midnight
    end: int

    @property
    def minutes(self) -> int:
        return self.end - self.start


def is_b23(type_: str) -> bool:
    return re.sub(r"[\s\-]", "", (type_ or "").upper()).startswith("B23")


def parse_fleet(daily: dict) -> list[Aircraft]:
    out = []
    for l in daily.get("lignes") or []:
        if (l.get("idType") or "acft") != "acft":
            continue
        out.append(Aircraft(int(l["id"]), (l.get("content") or "").strip(), (l.get("complementaryContent") or "").strip()))
    return out


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:12], "%Y%m%d%H%M")


def _clip(day: date, a: str, b: str) -> tuple[int, int] | None:
    d0 = datetime.combine(day, datetime.min.time())
    s, e = _dt(a), _dt(b)
    if e <= s and e.time() == datetime.min.time() and e.date() == s.date():
        e = e + timedelta(days=1)  # "...0000" end == midnight next day
    s_m = max(0, int((s - d0).total_seconds() // 60))
    e_m = min(1440, int((e - d0).total_seconds() // 60))
    return (s_m, e_m) if e_m > s_m else None


def _subtract(free: list[tuple[int, int]], busy: list[tuple[int, int]]) -> list[tuple[int, int]]:
    for bs, be in sorted(busy):
        nxt = []
        for fs, fe in free:
            if be <= fs or bs >= fe:
                nxt.append((fs, fe))
                continue
            if bs > fs:
                nxt.append((fs, bs))
            if be < fe:
                nxt.append((be, fe))
        free = nxt
    return free


def free_slots_for_line(reg: str, line: dict, day: date, min_minutes: int = 30,
                        exclude_civil_night: bool = False, not_before: int = 0) -> list[Slot]:
    blocked_colors = {COLOR_UNAVAILABLE, COLOR_AERO_NIGHT}
    if exclude_civil_night:
        blocked_colors.add(COLOR_CIVIL_NIGHT)
    busy: list[tuple[int, int]] = []
    for b in line.get("couleursFond") or []:
        if (b.get("color") or "").lower() in blocked_colors:
            c = _clip(day, b["debut"], b["fin"])
            if c:
                busy.append(c)
    resas = [r for s in line.get("sublignes") or [] for r in s.get("reservations") or []]
    for r in resas + list(line.get("reservationsFlottantes") or []):
        c = _clip(day, r["debut"], r["fin"])
        if c:
            busy.append(c)
    if not_before > 0:
        busy.append((0, not_before))
    free = _subtract([(0, 1440)], busy)
    return [Slot(reg, day, s, e) for s, e in free if e - s >= min_minutes]


def parse_aircraft_planning(reg: str, data: dict, min_minutes: int = 30,
                            exclude_civil_night: bool = False,
                            now: datetime | None = None) -> dict[date, list[Slot]]:
    """GetPlanningAircraft: one line per day (≈30 days). Past time of today is excluded."""
    out: dict[date, list[Slot]] = {}
    for l in data.get("lignes") or []:
        day = _dt(l["debut"]).date()
        if now is not None and day < now.date():
            continue
        nb = now.hour * 60 + now.minute if (now is not None and day == now.date()) else 0
        out[day] = free_slots_for_line(reg, l, day, min_minutes, exclude_civil_night, nb)
    return out


def fmt_hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}" if m < 1440 else "24:00"


JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
BASE_URL = "https://online.aerogest.fr"


def planning_link(day: date) -> str:
    return f"{BASE_URL}/Schedule/planning/daily/{day:%Y%m%d}"


def format_alert(slot: Slot, type_: str = "B23") -> str:
    return (f"✈️ Créneau libre — {slot.reg} ({type_})\n"
            f"{JOURS[slot.day.weekday()]} {slot.day:%d/%m} · {fmt_hm(slot.start)}–{fmt_hm(slot.end)}\n"
            f"{planning_link(slot.day)}")
