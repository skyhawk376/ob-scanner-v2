"""v3 Telegram messages (French, concise) — one per (zone, event)."""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from . import params as P

PARIS = ZoneInfo("Europe/Paris")
TF_LABEL = {"M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4", "D": "Daily", "W": "Weekly"}
STAR_NAMES = (("tendance", "Tendance"), ("liquidite", "Liquidité prise"), ("vierge", "Jamais touché"),
              ("fibo", "Fibo 0.5"), ("session", "Session"))


def px(v: float | None) -> str:
    if v is None:
        return "—"
    a = abs(v)
    d = 2 if a >= 100 else 4 if a >= 1 else 5 if a >= 0.01 else 8
    if a >= 10000:
        d = 1
    return f"{v:.{d}f}"


def hm(ts: str | None) -> str:
    if not ts:
        return "?"
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(PARIS).strftime("%d/%m %H:%M")


def stars_str(score: int) -> str:
    return "★" * score + "☆" * (5 - score)


def side(z: dict) -> str:
    return "ACHAT" if z["direction"] == "bull" else "VENTE"


def fmt_touch(z: dict, ev: dict, res: dict) -> str:
    st = ev.get("stars") or {}
    score = int(ev.get("score") or 0)
    checks = " ".join(("✅ " if st.get(k) else "✖️ ") + name for k, name in STAR_NAMES)
    t = res["touches"][int(ev["key"].replace("touch", "")) - 1] if res.get("touches") else {}
    ltf = TF_LABEL[P.LOWER_TF[z["tf"]]]
    return (
        f"🟡 Zone touchée — prépare-toi\n"
        f"{z['symbol']} · {TF_LABEL[z['tf']]} · {side(z)} · {stars_str(score)} ({score}/5)\n"
        f"Zone {px(z['low'])} – {px(z['high'])}\n"
        f"{checks}\n"
        f"Attends une bougie de retournement en {ltf} (englobante ou marteau) avant {hm(t.get('window_end'))}.\n"
        f"SL prévu ≈ {px(res.get('sl'))} (au-delà de l'OB)"
    )


def fmt_entry(z: dict, res: dict) -> str:
    tr = res["trade"]
    return (
        f"🟢 ENTRÉE {side(z)} — {z['symbol']} {TF_LABEL[z['tf']]} ({stars_str(int(tr.get('score') or 0))})\n"
        f"Déclencheur : {tr['trigger']} {TF_LABEL[tr['ltf']]} (clôture {hm(tr['entry_ts'])})\n"
        f"Entrée : {px(tr['entry'])} (au marché)\n"
        f"SL : {px(tr['sl'])} · TP (+{P.TP_R:g}R) : {px(tr['tp'])}\n"
        f"À +1R ({px(tr['be_level'])}) : SL au point d'entrée."
    )


def fmt_be(z: dict, res: dict) -> str:
    tr = res["trade"]
    return (
        f"🔵 {z['symbol']} {TF_LABEL[z['tf']]} {side(z)} : +1R atteint\n"
        f"Passe ton SL au point d'entrée ({px(tr['entry'])})."
    )


def fmt_exit(z: dict, res: dict) -> str:
    tr = res["trade"]
    r = tr.get("r_net")
    net = f"{r:+.2f}R net (frais estimés)" if r is not None else ""
    head = {"tp": f"✅ TP +{P.TP_R:g}R", "sl": "❌ SL −1R", "be_exit": "⚪ Break-even 0R"}.get(tr["exit"], tr["exit"])
    return (
        f"{head} — {z['symbol']} {TF_LABEL[z['tf']]} {side(z)}\n"
        f"Entrée {px(tr['entry'])} → sortie {hm(tr['exit_ts'])} · {net}"
    )


def format_event(z: dict, ev: dict, res: dict) -> str:
    k = ev["kind"]
    if k == "touch":
        return fmt_touch(z, ev, res)
    if k == "entry":
        return fmt_entry(z, res)
    if k == "be":
        return fmt_be(z, res)
    if k == "exit":
        return fmt_exit(z, res)
    raise ValueError(k)


def max_age_sec(kind: str, tf: str) -> float | None:
    """Staleness limit for touch/entry alerts; be/exit follow the entry (no limit)."""
    if kind in ("be", "exit"):
        return None
    ltf_min = P.TF_MIN[P.LOWER_TF[tf]]
    return max(P.ALERT_MIN_AGE_MIN * 60.0, 2 * ltf_min * 60.0)


def sample_messages() -> dict[str, str]:
    z = {"symbol": "XAUUSD", "tf": "H1", "direction": "bull", "low": 2391.2, "high": 2394.8}
    stars = {"tendance": True, "liquidite": True, "vierge": True, "fibo": True, "session": False}
    res = {"sl": 2390.95, "touches": [{"window_end": "2026-10-09T12:00:00Z"}],
           "trade": {"trigger": "englobante", "ltf": "M15", "entry_ts": "2026-10-09T09:45:00Z",
                     "entry": 2395.10, "sl": 2390.95, "tp": 2403.40, "be_level": 2399.25, "score": 4,
                     "exit": "tp", "exit_ts": "2026-10-09T13:15:00Z", "r_net": 1.91}}
    ev = {"kind": "touch", "key": "touch1", "score": 4, "stars": stars}
    out = {"touch": format_event(z, ev, res), "entry": fmt_entry(z, res), "be": fmt_be(z, res),
           "exit_tp": fmt_exit(z, res)}
    for ex, r in (("sl", -1.06), ("be_exit", -0.06)):
        res2 = {**res, "trade": {**res["trade"], "exit": ex, "r_net": r}}
        out[f"exit_{ex}"] = fmt_exit(z, res2)
    return out
