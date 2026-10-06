"""EXPLORATORY (NOT pre-registered; added after the pre-registered grid failed). Same simulator, costs and split.
X1  Intraday momentum on US index CFDs (Gao-Han-Li-Zhou 2018 'market intraday momentum'): at 15:30 New York
    (21:30 Paris) go with the sign of (a) the first half-hour return (prev 16:00 close -> 10:00) or (b) the
    09:30 -> 15:30 return; market entry 3 min later, exit 16:00 NY (time stop), protective SL 1 ATR(H1), no TP.
Also: gross (zero-cost) per-group breakdown of the best zero-cost config of each family (diagnostic)."""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from common import OUT, TEST, TRAIN, asof, local, metrics, simulate, split
from families import _req, _to_utc

def x1_requests(pred: str, syms=("US500", "NAS100")) -> pd.DataFrame:
    rows = []
    for sym in syms:
        df = local(sym, "America/New_York")
        df = df[df.dow < 5]
        c = df.set_index(["date", "mod"])["close"]
        def at(m):
            s = c.xs(m, level=1, drop_level=True) if m in c.index.get_level_values(1) else None
            return s
        c1559 = at(15 * 60 + 59); c0959 = at(9 * 60 + 59); c1529 = at(15 * 60 + 29)
        o0930 = df[df["mod"] == 9 * 60 + 30].set_index("date")["open"]
        d = pd.concat([c1559.rename("c1559"), c0959.rename("c0959"), c1529.rename("c1529"), o0930.rename("o0930")], axis=1, sort=True)
        d["prev_close"] = d["c1559"].shift(1)
        d = d.dropna()
        r = (d.c0959 / d.prev_close - 1) if pred == "first30" else (d.c1529 / d.o0930 - 1)
        t_sig = _to_utc(pd.Series(d.index), 15 * 60 + 30, "America/New_York")
        atr = asof(sym, "H1", t_sig, "atr")
        for k, (date, row) in enumerate(d.iterrows()):
            side = 1 if r.iloc[k] > 0 else -1
            ref = row.c1529
            rows.append(_req(sym=sym, t_active=t_sig[k] + pd.Timedelta(minutes=3), side=side, etype="market", level=ref,
                             sl=ref - side * atr[k], tp_r=99.0, hold_min=27.0, sig_time=t_sig[k]))
    return pd.DataFrame(rows)

def x2_requests(floor_atr_h1: float, syms=("XAUUSD", "XAGUSD", "EURUSD", "USDCAD", "NAS100", "US500")) -> pd.DataFrame:
    """X2 (exploratory): D_FVG US/H4/mid/gap/TP2 signal (best zero-cost config on TRAIN, gross edge in both periods),
    but SL pushed to at least `floor_atr_h1` x ATR(H1) from entry so costs are a smaller share of R. Crypto excluded
    (gross ~0 on TRAIN and highest cost/risk)."""
    import families as F
    a, b, _ = F.FVG_WIN["US"]
    rows = []
    for sym in syms:
        f = F._fvg_all(sym)
        f = f[(f["mod"] > a) & (f["mod"] <= b) & (f["dow"] < 5) & (f["side"] == f["H4"])].groupby("date").head(1)
        atr_h1 = asof(sym, "H1", f["t_sig"], "atr")
        for k, r in enumerate(f.itertuples()):
            lvl = (r.prox + r.far) / 2
            sl = r.far - 0.1 * r.atr if r.side > 0 else r.far + 0.1 * r.atr
            min_d = floor_atr_h1 * atr_h1[k]
            if abs(lvl - sl) < min_d:
                sl = lvl - r.side * min_d
            rows.append(_req(sym=sym, t_active=r.t_sig + pd.Timedelta(minutes=3), side=int(r.side), etype="limit",
                             level=float(lvl), sl=float(sl), tp_r=2.0, expiry_min=120.0, sig_time=r.t_sig))
    return pd.DataFrame(rows)

def main():
    out = {}
    for pred in ("first30", "daysofar"):
        req = x1_requests(pred)
        for cm in (0.0, 1.0, 1.5):
            tr = simulate(req, cost_mult=cm)
            a, b = split(tr)
            out[f"X1_{pred}_cost{cm:g}"] = dict(train=metrics(a, TRAIN), test=metrics(b, TEST),
                                                train_by_sym={s: metrics(g, TRAIN)["avg"] for s, g in a.groupby("sym")},
                                                test_by_sym={s: metrics(g, TEST)["avg"] for s, g in b.groupby("sym")})
            print(pred, cm, "train", round(out[f"X1_{pred}_cost{cm:g}"]["train"]["avg"], 3), out[f"X1_{pred}_cost{cm:g}"]["train"]["n"],
                  "test", round(out[f"X1_{pred}_cost{cm:g}"]["test"]["avg"], 3), out[f"X1_{pred}_cost{cm:g}"]["test"]["n"], flush=True)
    for fl in (0.0, 0.5, 1.0):
        req = x2_requests(fl)
        for cm in (0.0, 1.0, 1.5):
            tr = simulate(req, cost_mult=cm)
            a, b = split(tr)
            key = f"X2_fvgUS_floor{fl:g}_cost{cm:g}"
            out[key] = dict(train=metrics(a, TRAIN), test=metrics(b, TEST),
                            train_by_sym={s: metrics(g, TRAIN)["avg"] for s, g in a.groupby("sym")},
                            test_by_sym={s: metrics(g, TEST)["avg"] for s, g in b.groupby("sym")})
            print(key, "train", round(out[key]["train"]["avg"], 3), out[key]["train"]["n"], "test", round(out[key]["test"]["avg"], 3),
                  out[key]["test"]["n"], "CI", round(out[key]["test"]["lo"], 3), round(out[key]["test"]["hi"], 3), flush=True)
    (OUT / "exploratory_x1.json").write_text(json.dumps(out, indent=1, default=float))

if __name__ == "__main__":
    main()
