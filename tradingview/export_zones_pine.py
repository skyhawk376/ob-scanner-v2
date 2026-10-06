#!/usr/bin/env python3
"""Génère un indicateur Pine *statique* avec les zones EXACTES du scanner (prod) pour un
symbole — niveaux 1:1 (entrée / SL / TP +2R) lus sur l'API, lecture seule (GET /zones).

Usage :
    python tradingview/export_zones_pine.py XAUUSD                      # zones actives (vierges)
    python tradingview/export_zones_pine.py XAUUSD --statuses all       # + historiques
    python tradingview/export_zones_pine.py EURUSD --tf H1,H4 -o /tmp/eurusd.pine

Puis TradingView → Pine Editor → coller le fichier → Ajouter au graphique. Le fichier est
une photo à l'instant T : le relancer pour rafraîchir. Les niveaux sont ceux du flux du
scanner (or = futures COMEX GC=F → utiliser COMEX:GC1! ; crypto = Binance ; forex = Yahoo).
Aucune dépendance (stdlib) ; aucun secret requis (API publique en lecture).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://ob-scanner-v2.fly.dev"
TF_LABEL = {"M5": "M5", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4", "D": "D1", "W": "W1"}
TF_RANK = {"W": 0, "D": 1, "H4": 2, "H1": 3, "M30": 4, "M15": 5, "M5": 6}
STATUS_FR = {"active": "", "touchee": "touchée", "reaction": "réaction +2R", "echec": "échec SL", "expiree": "expirée"}
TV_HINT = {"XAUUSD": "COMEX:GC1!", "XAGUSD": "COMEX:SI1!", "XPTUSD": "NYMEX:PL1!", "XPDUSD": "NYMEX:PA1!",
           "COPPER": "COMEX:HG1!"}


def fetch_zones(symbol: str, api: str, statuses: str, min_score: int, tfs: list[str] | None) -> list[dict]:
    q = {"symbol": symbol, "min_score": min_score, "limit": 1000}
    if statuses == "active":
        q["active_only"] = "true"
    elif statuses != "all":
        q["statuses"] = statuses
    url = f"{api.rstrip('/')}/zones?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        zones = json.load(r)["zones"]
    if statuses == "active":
        zones = [z for z in zones if (z.get("status") or "active") == "active"]
    if tfs:
        zones = [z for z in zones if z.get("tf") in tfs]
    zones.sort(key=lambda z: (TF_RANK.get(z.get("tf"), 9), z.get("ts_ob", "")))
    return zones


def _ms(iso: str | None) -> int:
    if not iso:
        return 0
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _f(x) -> str:
    return "na" if x is None else repr(float(x))


def stars(n: int) -> str:
    n = max(0, min(5, int(n or 0)))
    return "★" * n + "☆" * (5 - n)


def render(symbol: str, zones: list[dict], api: str, statuses: str) -> str:
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
    stamp = now.strftime("%Y-%m-%d %H:%M")
    rows = []
    for z in zones:
        st = z.get("status") or "active"
        txt = f"{stars(z.get('score'))} {TF_LABEL.get(z.get('tf'), z.get('tf'))}"
        if st != "active":
            txt += f" · {STATUS_FR.get(st, st)}"
        end = _ms(z.get("touched_at") or z.get("expired_at")) if st != "active" else 0
        rows.append(
            f"    f_zone({_ms(z['ts_ob'])}, {end}, {_f(z['high'])}, {_f(z['low'])}, {_f(z['entry'])}, "
            f"{_f(z['sl'])}, {_f(z.get('tp2'))}, {1 if z['direction'] == 'bull' else -1}, "
            f"{'true' if st == 'active' else 'false'}, \"{txt}\")"
        )
    hint = TV_HINT.get(symbol, f"le symbole {symbol} du flux du scanner")
    body = "\n".join(rows) if rows else "    int noZone = 0  // aucune zone"
    n_act = sum(1 for z in zones if (z.get("status") or "active") == "active")
    return f'''// Zones EXACTES du scanner OB (prod) — {symbol} — export {stamp} (Paris)
// Généré par tradingview/export_zones_pine.py depuis {api}/zones (statuts : {statuses}).
// Photo figée : relancer le script pour mettre à jour. Niveaux du flux du scanner :
// à afficher de préférence sur {hint}.
// Installation : Pine Editor → coller → Enregistrer → Ajouter au graphique.
//@version=6
indicator("OB Scanner — zones {symbol} ({stamp})", shorttitle = "OB {symbol} live", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_labels_count = 500)
showSLTP = input.bool(true, "Lignes SL / TP (+2R)")
bullCol  = input.color(#26a69a, "Haussier")
bearCol  = input.color(#ef5350, "Baissier")
histCol  = input.color(#787b86, "Historique")

var array<box>  gBox = array.new<box>()
var array<line> gLin = array.new<line>()

f_zone(int t0, int t1, float top, float bot, float entry, float sl, float tp, int dir, bool act, string txt) =>
    color col = act ? (dir == 1 ? bullCol : bearCol) : histCol
    int right = act ? time : math.max(t1, t0 + 1)
    ext = act ? extend.right : extend.none
    gBox.push(box.new(t0, top, right, bot, xloc = xloc.bar_time, extend = ext, border_color = color.new(col, 35), bgcolor = color.new(col, act ? 82 : 90), text = txt, text_size = size.small, text_color = color.new(#d1d4dc, act ? 0 : 40), text_halign = text.align_left, text_valign = text.align_top))
    gLin.push(line.new(t0, entry, right, entry, xloc = xloc.bar_time, extend = ext, color = color.new(col, 20), style = line.style_dashed))
    if showSLTP and act
        gLin.push(line.new(t0, sl, right, sl, xloc = xloc.bar_time, extend = ext, color = color.new(bearCol, 30), style = line.style_dotted))
        gLin.push(line.new(t0, tp, right, tp, xloc = xloc.bar_time, extend = ext, color = color.new(bullCol, 30), style = line.style_dotted))
    true

if barstate.islast
    for bx in gBox
        bx.delete()
    for ln in gLin
        ln.delete()
    gBox.clear()
    gLin.clear()
{body}
    var table info = table.new(position.top_right, 1, 1)
    info.cell(0, 0, "Scanner OB {symbol} · {stamp} · actives : {n_act}", text_color = #d1d4dc, text_size = size.small, bgcolor = color.new(color.black, 70))
'''


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("--api", default=API)
    ap.add_argument("--statuses", default="active", help="active (défaut) | all | liste ex. active,touchee")
    ap.add_argument("--min-score", type=int, default=4)
    ap.add_argument("--tf", default="", help="filtre TF ex. H1,H4 (défaut : tous)")
    ap.add_argument("-o", "--out", default="")
    a = ap.parse_args()
    sym = a.symbol.upper()
    tfs = [t.strip().upper().replace("D1", "D").replace("W1", "W") for t in a.tf.split(",") if t.strip()] or None
    zones = fetch_zones(sym, a.api, a.statuses, a.min_score, tfs)
    out = Path(a.out) if a.out else Path(__file__).resolve().parent / "examples" / f"{sym}_live_zones.pine"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(sym, zones, a.api, a.statuses), encoding="utf-8")
    print(f"{len(zones)} zone(s) {sym} → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
