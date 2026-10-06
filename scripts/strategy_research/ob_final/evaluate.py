"""Detailed TEST evaluation of the frozen winners, management family D, random + trend baselines.
Usage: python evaluate.py  -> winners_detail.json, top10_<fam>.csv, baseline.json
"""
from __future__ import annotations
import json
import numpy as np, pandas as pd
import core as C
from grid import load, cfg_mask, WK_TRAIN, WK_TEST, WK_RECENT, SPLIT_NS, RECENT_NS

HOLD_MIN = {"3h": 180, "1d": 1440, "2d": 2880, "5d": 7200, "10d": 14400}
rng = np.random.default_rng(42)

def mstats(x: pd.DataFrame, wk: float, col="r_net"):
    x = x.sort_values("t_fill")
    m = C.metrics(x[col].to_numpy(float), wk)
    m["hold_h"] = float(x.hold_min.mean() / 60) if len(x) else np.nan
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}

def detail(D: pd.DataFrame, cfg: str, mgmt: int = 0) -> dict:
    m = cfg_mask(D, cfg) & (D.mgmt == mgmt).to_numpy()
    x = D[m]
    out = {"cfg": cfg, "mgmt": mgmt}
    for cost in (1.0, 1.5, 0.0):
        y = x[x.cost == cost]
        tr, te = y[y.t_fill < SPLIT_NS], y[y.t_fill >= SPLIT_NS]
        rc = y[y.t_fill >= RECENT_NS]
        out[f"c{cost}"] = {"train": mstats(tr, WK_TRAIN), "test": mstats(te, WK_TEST), "recent": mstats(rc, WK_RECENT)}
    y = x[x.cost == 1.0].copy()
    ts = pd.to_datetime(y.t_fill, utc=True)
    y["year"] = ts.dt.year; y["q"] = ts.dt.to_period("Q").astype(str)
    out["per_year"] = y.groupby("year").r_net.agg(["size", "mean"]).round(3).reset_index().values.tolist()
    te = y[y.t_fill >= SPLIT_NS]
    out["test_quarters"] = te.groupby("q").r_net.agg(["size", "mean"]).round(3).reset_index().values.tolist()
    out["test_years_pos"] = int((te.groupby("year").r_net.mean() > 0).sum()); out["test_years"] = int(te.year.nunique())
    out["test_q_pos"] = int((te.groupby("q").r_net.mean() > 0).sum()); out["test_q"] = int(te.q.nunique())
    for nm, part in (("train", y[y.t_fill < SPLIT_NS]), ("test", te)):
        out[f"group_{nm}"] = part.groupby("group").r_net.agg(["size", "mean"]).round(3).reset_index().values.tolist()
        out[f"sym_{nm}"] = part.groupby("sym").r_net.agg(["size", "mean"]).round(3).reset_index().values.tolist()
        out[f"side_{nm}"] = part.groupby("side").r_net.agg(["size", "mean"]).round(3).reset_index().values.tolist()
        out[f"why_{nm}"] = part.why.value_counts().sort_index().to_dict()
    out["cost_over_risk_median"] = float(((x[x.cost == 1.0].r_gross.values.mean() - x[x.cost == 1.0].r_net.values.mean())))
    return out

def baselines(D: pd.DataFrame, cfg: str, trend_col: str | None, draws: int = 5) -> dict:
    """prereg random baseline (random side) + exploratory trend baseline (side = D1 EMA trend at the random time)."""
    x = D[cfg_mask(D, cfg) & (D.mgmt == 0).to_numpy() & (D.cost == 1.0).to_numpy()]
    res = {"random": [], "trend": []}
    for sym, g in x.groupby("sym"):
        A = C.m1_arrays(sym); t = A["t"]
        d1 = C.tf_bars(sym, "D1") if trend_col else None
        tf_ = pd.to_datetime(g.t_fill.to_numpy(), utc=True)
        mstart = tf_.to_period("M").to_timestamp().tz_localize("UTC")
        mend = (tf_.to_period("M") + 1).to_timestamp().tz_localize("UTC")
        lo = np.searchsorted(t, mstart.as_unit("ns").asi8); hi = np.searchsorted(t, mend.as_unit("ns").asi8)
        riskf = (g.risk / g.epx).to_numpy(); rr = (np.abs(g.tp_px - g.epx) / g.risk).to_numpy()
        hold = g.hold.map(HOLD_MIN).to_numpy()
        for d in range(draws):
            idx = []
            for a, b in zip(lo, hi):
                for _ in range(20):
                    i = int(rng.integers(a, max(b, a + 1)))
                    if i < len(t) and pd.Timestamp(t[i], tz="UTC").dayofweek < 5: break
                idx.append(min(i, len(t) - 2))
            idx = np.array(idx, np.int64)
            for kind in ("random", "trend"):
                if kind == "trend" and not trend_col: continue
                side = rng.choice([-1, 1], len(idx)) if kind == "random" else C.d1_trend(d1, t[idx], {"tr20": "ema20", "tr50": "ema50"}[trend_col]).astype(np.int64)
                side = np.where(side == 0, 1, side).astype(np.int64)
                for cost in (1.0, 0.0):
                    sp, cm, sl = zip(*[C.costs(sym, p) for p in A["o"][idx]])
                    hs = np.array(sp) * cost / 2; cm = np.array(cm) * cost; sl = np.array(sl) * cost
                    f, e, _ = C.find_fill(t, A["o"], A["h"], A["l"], A["c"], idx, side, np.zeros(len(idx), np.int64), A["o"][idx], np.zeros(len(idx), np.int64), hs)
                    epx = e + side * sl; risk = riskf * epx; S = epx - side * risk; T = epx + side * rr * risk
                    xx, r, w, rk, ep = C.run_exit(t, A["o"], A["h"], A["l"], A["c"], f, side, np.zeros(len(idx), np.int64), e, A["o"][idx], S, T,
                                                  (hold * 60e9).astype(np.int64), hs, sl, 0, np.full(len(t), -np.inf), np.full(len(t), np.inf))
                    days = (t[np.maximum(xx, 0)] - t[f]) / 86400e9
                    net = r - cm / rk - (C.swap_r(sym, side, ep, days, rk, cost) if cost > 0 else 0)
                    res[kind].append(pd.DataFrame({"sym": sym, "t_fill": t[f], "cost": cost, "r": net, "side": side}))
    out = {}
    for kind, parts in res.items():
        if not parts: continue
        b = pd.concat(parts)
        for cost in (1.0, 0.0):
            bb = b[b.cost == cost]
            for nm, part in (("train", bb[bb.t_fill < SPLIT_NS]), ("test", bb[bb.t_fill >= SPLIT_NS])):
                r = part.r.to_numpy(float)
                out[f"{kind}_{'net' if cost else 'gross'}_{nm}"] = dict(n=len(r), avg=round(float(r.mean()), 4),
                                                                        lo=round(float(r.mean() - 1.96 * r.std(ddof=1) / np.sqrt(len(r))), 4),
                                                                        hi=round(float(r.mean() + 1.96 * r.std(ddof=1) / np.sqrt(len(r))), 4),
                                                                        long_share=round(float((part.side > 0).mean()), 3))
    return out

def verdict(det: dict, base: dict) -> str:
    te = det["c1.0"]["test"]; te15 = det["c1.5"]["test"]
    if not (te["n"] and te["avg"] > 0): return "FAIL"
    ok = (te["lo"] > 0) and (te15["avg"] > 0) and (det["test_years_pos"] >= 3) and (te["avg"] > base.get("random_net_test", {}).get("avg", 9))
    return "VIABLE" if ok else "WEAK"

if __name__ == "__main__":
    sel = json.loads((C.OUT / "selection.json").read_text())
    D = load()  # all costs, all mgmt
    out = {}
    for fam in ("A", "B", "C", "EA", "EB", "EC"):
        cfg = sel[fam]["winner"]
        det = detail(D, cfg, 0)
        tc = cfg.split("|")[4] if fam in ("A", "C", "EA", "EC") else cfg.split("|")[3]
        base = baselines(D, cfg, tc if tc != "none" else None)
        det["baseline"] = base; det["verdict"] = verdict(det, base)
        det["prereg"] = fam in ("A", "B", "C", "EA")
        out[fam] = det
        te = det["c1.0"]["test"]
        print(fam, cfg, det["verdict"], "TEST", te["n"], te["avg"], te["lo"], te["hi"], "1.5x", det["c1.5"]["test"]["avg"],
              "gross", det["c0.0"]["test"]["avg"], "yrs+", det["test_years_pos"], "/", det["test_years"],
              "rand", base.get("random_net_test", {}).get("avg"), "trendbase", base.get("trend_net_test", {}).get("avg"), flush=True)
    # family D: management on the overall best family winner (highest TRAIN t among A/B/C winners)
    best = max(("A", "B", "C"), key=lambda f: out[f]["c1.0"]["train"]["t"])
    out["best_family"] = best
    for fam_, tag in ((best, "D"), ("C", "D_C_explor")):
        cfg = sel[fam_]["winner"]
        res = {}
        for mg in (0, 1, 2, 3):
            det = detail(D, cfg, mg)
            res[mg] = {k: det[k] for k in ("c1.0", "c1.5", "c0.0", "per_year", "test_years_pos", "test_years", "test_q_pos", "test_q")}
            print(tag, cfg, "mgmt", mg, "TRAIN", det["c1.0"]["train"]["avg"], det["c1.0"]["train"]["t"], "TEST", det["c1.0"]["test"]["n"],
                  det["c1.0"]["test"]["avg"], det["c1.0"]["test"]["lo"], det["c1.0"]["test"]["hi"], flush=True)
        out[tag] = res
    (C.OUT / "winners_detail.json").write_text(json.dumps(out, indent=1, default=str))
    for fam in ("A", "B", "C", "EA", "EB", "EC"):
        g = pd.read_csv(C.OUT / f"grid_{fam}.csv")
        g = g[(g.train_n >= 100) & (g.train_per_wk >= 0.25)].sort_values("train_t", ascending=False).head(10)
        g.to_csv(C.OUT / f"top10_{fam}.csv", index=False)
