"""Parité Pine (port Python `pine_reference.py`) vs moteur du scanner (prod).

Usage :
    /tmp/obv/bin/python tradingview/parity_check.py --dir /tmp/tvcmp [--step 5]

Pour chaque fichier `<SYM>_<TF>.json` (format de GET /candles/{symbol}?tf=..&limit=5000)
on simule des « scans » à plusieurs instants T (toutes les `step` barres) :
  scanner = detect_zones(df[:T+1]) (la dernière barre est ignorée comme en prod)
            filtré par simulate_lifecycle(...).status == "active"  (zones listées)
  pine    = PineEngine rejoué jusqu'à la barre T-1, zones actives ≥ 4★
et on compare les ensembles (clé = sens + horodatage de l'OB) et les étoiles.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.core.lifecycle import simulate_lifecycle  # noqa: E402
from backend.app.engine.detect import detect_zones  # noqa: E402
from backend.app.engine.params import params_for_tf  # noqa: E402
from pine_reference import STATUS_NAME, PineEngine, epoch_seconds  # noqa: E402


def load(path: str) -> pd.DataFrame:
    d = json.load(open(path))
    df = pd.DataFrame(d["candles"])
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def scanner_active(df: pd.DataFrame, T: int, tf: str, min_score: int = 4) -> dict:
    zs = detect_zones(df.iloc[: T + 1], symbol="X", tf=tf, params=params_for_tf(tf),
                      min_score=min_score, require_fresh=True)
    closed = df.iloc[:T]
    out = {}
    for z in zs:
        d = z.to_dict()
        if simulate_lifecycle(closed, d, require_entry_fill=False).status != "active":
            continue
        key = (z.direction, int(pd.Timestamp(z.ts_ob).timestamp()))
        out[key] = (z.star1_fvg, z.star2_trend, z.star3_fib, z.star4_liquidity, z.star5_session,
                    round(z.entry, 8), round(z.sl, 8))
    return out


def pine_active(eng: PineEngine, min_score: int = 4) -> dict:
    out = {}
    for z in eng.active(min_score):
        key = ("bull" if z.bull else "bear", z.ob_time)
        s5 = z.s5 if not z.pending else False
        out[key] = (z.s1, z.s2, z.s3(), z.s4, s5, round(z.entry, 8), round(z.sl, 8))
    return out


def load_any(path: str, tf: str | None = None, bars: int = 0) -> tuple[str, str, pd.DataFrame]:
    """JSON /candles ou parquet de recherche (`<SYM>_<TF>.parquet`, rééchantillonnable via tf)."""
    name = os.path.basename(path).rsplit(".", 1)[0]
    sym, tf0 = name.rsplit("_", 1)
    if path.endswith(".json"):
        df = load(path)
    else:
        df = pd.read_parquet(path)[["open", "high", "low", "close"]].astype(float)
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    if tf and tf != tf0:
        rule = {"H1": "1h", "H4": "4h", "M30": "30min"}[tf]
        df = df.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        tf0 = tf
    if bars and len(df) > bars:
        df = df.iloc[-bars:]
    return sym, tf0, df


def compare(path: str, step: int = 1, verbose: bool = False, tf: str | None = None,
            bars: int = 0, scans: int = 300) -> dict:
    """Scans simulés à chaque barre T des `scans` dernières barres (step 1 conseillé).

    Écarts classés :
      lag        : zone du scanner dont le BOS est sur les N-1 dernières barres ; le Pine
                   l'affiche 1-2 barres plus tard (pivots pas encore confirmés) ;
      transient  : zone listée par le scanner puis retirée au scan suivant (repaint du
                   scanner : un pivot confirmé ensuite annule le BOS) ;
      réel       : tout le reste (vrai désaccord de logique).
    """
    sym, tf, df = load_any(path, tf, bars)
    name = f"{sym}_{tf}"
    t = epoch_seconds(df.index)
    eng = PineEngine(df.open.values, df.high.values, df.low.values, df.close.values, t, tf)
    D = eng.N - 1
    start = min(len(df) - 1, max(60, len(df) - scans))
    Ts = list(range(start, len(df) + 1, step))
    S, P = {}, {}
    for T in Ts:
        eng.run_to(T - 1)
        S[T] = scanner_active(df, T, tf)
        P[T] = pine_active(eng)
    both = only_s = only_p = star_eq = lvl_eq = lag = trans = 0
    real = []
    for T in Ts:
        s, p = S[T], P[T]
        ks, kp = set(s), set(p)
        both += len(ks & kp)
        for k in ks & kp:
            star_eq += s[k][:5] == p[k][:5]
            lvl_eq += (abs(s[k][5] - p[k][5]) <= 1e-9 * abs(s[k][5]) and abs(s[k][6] - p[k][6]) <= 1e-9 * abs(s[k][6]))
        for k in ks - kp:
            only_s += 1
            nxt = [T + d * step for d in range(1, D + 2) if T + d * step in P]
            if any(k in P[x] for x in nxt):
                lag += 1
            elif nxt and not all(k in S[x] for x in nxt[:1]):
                trans += 1
            else:
                real.append((T, k, s[k], None))
        for k in kp - ks:
            only_p += 1
            real.append((T, k, None, p[k]))
    union = both + only_s + only_p
    res = dict(file=name, bars=len(df), scans=len(Ts), both=both, only_scanner=only_s, only_pine=only_p,
               lag=lag, transient=trans, real=len(real),
               match=(both / union if union else 1.0),
               match_adj=((both + lag + trans) / union if union else 1.0),
               stars=(star_eq / both if both else 1.0), levels=(lvl_eq / both if both else 1.0))
    if verbose:
        for d in real[:10]:
            print("   réel", d)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/tvcmp", help="dossier des JSON /candles")
    ap.add_argument("--parquet", default="", help="glob de parquets longs (recherche)")
    ap.add_argument("--tf", default="", help="rééchantillonner les parquets (M30/H1/H4)")
    ap.add_argument("--bars", type=int, default=0, help="garder les N dernières barres")
    ap.add_argument("--scans", type=int, default=300, help="nb de scans simulés (dernières barres)")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    files = sorted(glob.glob(a.parquet)) if a.parquet else sorted(glob.glob(os.path.join(a.dir, "*_*.json")))
    if a.only:
        files = [f for f in files if any(x in os.path.basename(f) for x in a.only.split(","))]
    tot = defaultdict(float)
    print(f"{'série':<14}{'scans':>6}{'both':>7}{'scan':>6}{'pine':>6}{'lag':>5}{'trans':>6}{'réel':>5}"
          f"{'match':>8}{'adj':>8}{'★ ok':>8}{'lvl ok':>8}")
    for f in files:
        r = compare(f, a.step, a.v, a.tf or None, a.bars, a.scans)
        for k in ("both", "only_scanner", "only_pine", "lag", "transient", "real"):
            tot[k] += r[k]
        tot["stars"] += r["stars"] * r["both"]
        tot["levels"] += r["levels"] * r["both"]
        print(f"{r['file']:<14}{r['scans']:>6}{r['both']:>7}{r['only_scanner']:>6}{r['only_pine']:>6}"
              f"{r['lag']:>5}{r['transient']:>6}{r['real']:>5}"
              f"{r['match']:>8.1%}{r['match_adj']:>8.1%}{r['stars']:>8.1%}{r['levels']:>8.1%}", flush=True)
    u = tot["both"] + tot["only_scanner"] + tot["only_pine"]
    if u:
        print(f"TOTAL zone×scan: both={tot['both']:.0f} scanner_only={tot['only_scanner']:.0f} "
              f"(lag={tot['lag']:.0f} transient={tot['transient']:.0f}) pine_only={tot['only_pine']:.0f} "
              f"réels={tot['real']:.0f} | match brut={tot['both']/u:.2%} "
              f"hors lag/repaint scanner={(tot['both']+tot['lag']+tot['transient'])/u:.2%} "
              f"★={tot['stars']/max(1, tot['both']):.2%} niveaux={tot['levels']/max(1, tot['both']):.2%}")


if __name__ == "__main__":
    main()


def history_parity(path: str, tf: str | None = None, bars: int = 0, scans: int = 300,
                   intrabar: bool = True) -> dict:
    """Cycle de vie : simule la base du scanner (scan → upsert → lifecycle à chaque barre,
    comme le pipeline live, sans la reconstruction quotidienne « history » de 06:30) et la
    compare aux zones listées par le Pine (actives + touchées/réaction/échec/expirées).

    intrabar=True : le refresh lifecycle voit la barre T (en cours) avant que le scan
    suivant ne la voie clôturée (cas d'un refresh en fin de barre). intrabar=False : le
    refresh ne voit que les barres clôturées → le scan supprime d'abord la zone touchée
    (encore « active ») : elle disparaît de la base sans passer par « touchée »."""
    sym, tf, df = load_any(path, tf, bars)
    t = epoch_seconds(df.index)
    eng = PineEngine(df.open.values, df.high.values, df.low.values, df.close.values, t, tf)
    start = min(len(df) - 1, max(60, len(df) - scans))
    db: dict = {}
    for T in range(start, len(df) + 1):
        zs = detect_zones(df.iloc[: T + 1], symbol="X", tf=tf, params=params_for_tf(tf), min_score=4, require_fresh=True)
        ids = set()
        for z in zs:
            d = z.to_dict()
            key = (z.direction, int(pd.Timestamp(z.ts_ob).timestamp()))
            ids.add(key)
            if key not in db or db[key]["status"] == "active":
                d["status"] = "active"
                db[key] = d
        for key in [k for k, v in db.items() if v["status"] == "active" and k not in ids]:
            del db[key]
        closed = df.iloc[: T + 1] if intrabar else df.iloc[:T]
        for key, d in db.items():
            if d["status"] in ("active", "touchee"):
                life = simulate_lifecycle(closed, d, require_entry_fill=False)
                d["status"] = life.status
                d["touched_at"] = life.touched_at
    eng.run_to(len(df) - 1)
    first_t = int(df.index[start].timestamp())
    pz = {}
    for z in eng.listed(4):
        key = ("bull" if z.bull else "bear", z.ob_time)
        pz[key] = STATUS_NAME[z.status]
    # zones listées par le Pine dont la BOS précède la 1re barre simulée → hors périmètre
    sz = {k: v["status"] for k, v in db.items()}
    pz = {k: v for k, v in pz.items() if k in sz or k[1] >= first_t}
    both = set(sz) & set(pz)
    st_eq = sum(sz[k] == pz[k] for k in both)
    return dict(file=f"{sym}_{tf}", scanner=len(sz), pine=len(pz), both=len(both),
                only_scanner=sorted(set(sz) - set(pz)), only_pine=sorted(set(pz) - set(sz)),
                status_eq=st_eq, status_diff=[(k, sz[k], pz[k]) for k in both if sz[k] != pz[k]])
