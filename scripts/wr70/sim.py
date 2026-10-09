"""Copy of strategy_research/common.py simulator + optional break-even (PREREG_WR70.md). BE off == common.simulate."""
from __future__ import annotations
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "strategy_research"))
import common as C  # noqa: E402

RES = HERE / "results"; RES.mkdir(exist_ok=True)
EVENTS = HERE.parents[0] / "reversal_entry/results/events.parquet"
ZONES = HERE.parents[0] / "ob_shape/results/hist_zones.parquet"
ENTRY = {"E1": "T0lat|limit|zone|{h}", "E2": "T3|retest|zone|{h}", "E3": "T5a|m1|sweep|{h}"}
FILTERS = ["all", "noM5", "noCrypto", "cost10", "H1H4"]
TPS = [0.3, 0.5, 0.75, 1.0]
PERIOD = {"train": C.TRAIN, "test": C.TEST}


@njit(cache=True)
def _sim(t, o, h, l, c, start_i, side, etype, level, sl, tp_r, expiry_ns, hold_ns, hs, slip, be_frac, comm):
    n_tr = start_i.shape[0]; N = t.shape[0]
    out_fill = np.full(n_tr, -1, np.int64); out_exit = np.full(n_tr, -1, np.int64)
    out_epx = np.full(n_tr, np.nan); out_xpx = np.full(n_tr, np.nan)
    out_risk = np.full(n_tr, np.nan); out_why = np.zeros(n_tr, np.int8); out_be = np.zeros(n_tr, np.int8)
    for j in range(n_tr):
        s = start_i[j]
        if s < 0 or s >= N:
            continue
        lng = side[j] > 0
        L = level[j]; S = sl[j]; H = hs[j]; sp = slip[j]
        f = -1; epx = np.nan
        if etype[j] == 0:
            f = s
            epx = o[s] + H + sp if lng else o[s] - H - sp
        else:
            tmax = t[s] + expiry_ns[j]
            k = s
            while k < N and t[k] < tmax:
                if etype[j] == 1:
                    if lng and l[k] <= L - H:
                        f = k; epx = min(L, o[k] + H); break
                    if (not lng) and h[k] >= L + H:
                        f = k; epx = max(L, o[k] - H); break
                else:
                    if lng and h[k] >= L - H:
                        f = k; epx = max(L, o[k] + H) + sp; break
                    if (not lng) and l[k] <= L + H:
                        f = k; epx = min(L, o[k] - H) - sp; break
                k += 1
        if f < 0:
            continue
        if etype[j] == 0:
            risk = (epx - S) if lng else (S - epx); ref = epx
        else:
            risk = (L - S) if lng else (S - L); ref = L
        if risk <= 0:
            out_why[j] = 5; out_fill[j] = f; continue
        T = ref + tp_r[j] * risk if lng else ref - tp_r[j] * risk
        BEtrig = ref + be_frac[j] * tp_r[j] * risk if lng else ref - be_frac[j] * tp_r[j] * risk
        BEstop = epx + comm[j] if lng else epx - comm[j]
        armed = False
        out_fill[j] = f; out_epx[j] = epx; out_risk[j] = risk
        tend = t[f] + hold_ns[j]
        k = f; done = False
        while k < N and t[k] < tend:
            if lng:
                if l[k] <= S + H:
                    out_exit[j] = k; out_xpx[j] = min(S, o[k] - H) - sp if k > f else S - sp; out_why[j] = 2; done = True; break
                tp_hit = (c[k] >= T + H) if k == f else (h[k] >= T + H)
                if tp_hit:
                    out_exit[j] = k; out_xpx[j] = T if k == f else max(T, o[k] - H); out_why[j] = 1; done = True; break
                if be_frac[j] > 0 and (not armed) and h[k] >= BEtrig:
                    armed = True; out_be[j] = 1
                    if BEstop > S:
                        S = BEstop
            else:
                if h[k] >= S - H:
                    out_exit[j] = k; out_xpx[j] = max(S, o[k] + H) + sp if k > f else S + sp; out_why[j] = 2; done = True; break
                tp_hit = (c[k] <= T - H) if k == f else (l[k] <= T - H)
                if tp_hit:
                    out_exit[j] = k; out_xpx[j] = T if k == f else min(T, o[k] + H); out_why[j] = 1; done = True; break
                if be_frac[j] > 0 and (not armed) and l[k] <= BEtrig:
                    armed = True; out_be[j] = 1
                    if BEstop < S:
                        S = BEstop
            k += 1
        if not done:
            kl = k - 1
            if kl < f:
                kl = f
            out_why[j] = 4 if k >= N else 3
            out_exit[j] = kl
            out_xpx[j] = c[kl] - H - sp if lng else c[kl] + H + sp
    return out_fill, out_exit, out_epx, out_xpx, out_risk, out_why, out_be


def simulate(req: pd.DataFrame, cost_mult: float = 1.0) -> pd.DataFrame:
    outs = []
    et_map = {"market": 0, "limit": 1, "stop": 2}
    for sym, g in req.groupby("sym", sort=False):
        A = C.arrays(sym); g = g.copy()
        ta = pd.DatetimeIndex(g["t_active"]).tz_convert("UTC").as_unit("ns").asi8
        si = np.searchsorted(A["t"], ta, side="left").astype(np.int64)
        px = g["level"].to_numpy(float)
        sp, cm, sl_ = zip(*[C.costs(sym, p) for p in px])
        sp = np.array(sp) * cost_mult; cm = np.array(cm) * cost_mult; sl_ = np.array(sl_) * cost_mult
        # BE stop offset uses the real commission even in the zero-cost run (same stop price in both runs)
        cm_real = np.array([C.costs(sym, p)[1] for p in px])
        res = _sim(A["t"], A["o"], A["h"], A["l"], A["c"], si, g["side"].to_numpy(np.int64),
                   g["etype"].map(et_map).to_numpy(np.int64), px, g["sl"].to_numpy(float), g["tp_r"].to_numpy(float),
                   (g["expiry_min"].to_numpy(float) * 6e10).astype(np.int64),
                   (g["hold_min"].to_numpy(float) * 6e10).astype(np.int64), sp / 2.0, sl_,
                   g.get("be", pd.Series(0.0, index=g.index)).to_numpy(float), cm_real)
        f, x, epx, xpx, risk, why, be = res
        g["fill_i"] = f; g["why"] = [C.WHY[int(w)] for w in why]; g["be_armed"] = be
        g["entry_px"] = epx; g["exit_px"] = xpx; g["risk"] = risk
        idx = A["index"]
        g["t_fill"] = [idx[i] if i >= 0 else pd.NaT for i in f]
        g["t_exit"] = [idx[i] if i >= 0 else pd.NaT for i in x]
        g["comm"] = cm
        outs.append(g)
    r = pd.concat(outs)
    r = r[r["why"].isin(["tp", "sl", "time", "eod"])].copy()
    sgn = r["side"].astype(float)
    r["r_gross"] = sgn * (r["exit_px"] - r["entry_px"]) / r["risk"]
    r["r_net"] = r["r_gross"] - r["comm"] / r["risk"]
    r["group"] = r["sym"].map(C.GROUP)
    return r.sort_values("t_fill").reset_index(drop=True)


def part(df, which):
    t = pd.DatetimeIndex(df.t0)
    return df[t < C.SPLIT] if which == "train" else df[t >= C.SPLIT]


def build_orders(EV, entry, hold, tp, be):
    e = EV[EV.cfg == ENTRY[entry].format(h=hold)].copy()
    e["tp_r"] = tp; e["hold_min"] = {"1h": 60, "3h": 180}[hold]; e["expiry_min"] = e.expiry; e["be"] = be
    e["entry"] = entry; e["holdc"] = hold
    e["rid"] = np.arange(len(e))
    return e


def run(EV, Z, entry, hold, tp, be):
    e = build_orders(EV, entry, hold, tp, be)
    g = simulate(e, 0.0).set_index("rid")
    n = simulate(e, 1.0)
    n["r_gross"] = n.rid.map(g.r_gross)
    n = n.join(Z[["tf"]], on="zid")
    n = n[n.side * (n.entry_px - n.sl) > 0].copy()
    n["cost_r"] = n.comm / n.risk
    n["hold_real_min"] = (n.t_exit - n.t_fill).dt.total_seconds() / 60
    return n


def apply_filter(t, f):
    if f == "all": return t
    if f == "noM5": return t[t.tf != "M5"]
    if f == "noCrypto": return t[t.group != "CRYPTO"]
    if f == "cost10": return t[t.cost_r <= 0.10]
    if f == "H1H4": return t[t.tf.isin(["H1", "H4"])]
    raise KeyError(f)


def row(tr, which):
    m = C.metrics(tr, PERIOD[which], "r_net")
    return dict(n=m["n"], per_day=m["per_wd"], wr=m["wr"], gross=tr.r_gross.mean() if len(tr) else np.nan,
                net=m["avg"], lo=m["lo"], hi=m["hi"], pf=m["pf"], maxdd=m["maxdd"],
                hold_min=tr.hold_real_min.mean() if len(tr) else np.nan)
