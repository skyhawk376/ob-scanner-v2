"""OB Scanner v1 realistic backtest, per asset (checkpointed).
Zones: v1 5-star OBs (causal replay, see v1_core.detect_causal) on M5/M15/H1 built from M1 history (2015/2017 -> 2026-09).
Configs (one trade per alerted OB, limit order live 3 min after the alert bar closes):
  native : entry proximal edge (v1 'entry'), SL = v1 SL (distal edge + v1 buffer), TP +2R, no v1 time exit
           -> safety cap HOLD_CAP so every trade closes; order valid EXPIRY (≈ v1 data window per TF)
  mid_1h : entry mid-zone, same SL (beyond distal edge + v1 buffer), TP +2R from mid, time stop 60 min
  mid_3h : same, time stop 180 min
Costs: ob_final conventions (common.costs spread/commission/slippage + swap per day, both sides pay), cost x1, x0 (gross), x1.5.
Simulation on the 1-minute path with ob_final.core.find_fill/run_exit (stop-first, TP on fill bar only on close beyond).
Random baseline: per trade, a random weekday minute in the same symbol & month, random side, market entry,
same risk % of price, same TP in R, same max hold; 3 draws.
Usage: python run_v1.py SYM [SYM...] | all     (NPROC env, default 4)
"""
from __future__ import annotations
import os, sys, time
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "ob_final")); sys.path.insert(0, str(HERE.parent))
import core as C          # noqa: E402  (ob_final core: data, costs, simulator)
import v1_core as V       # noqa: E402

# v1 watchlist -> available long M1 history (US30, RUSSELL, NZDUSD, OIL: no long history on the box -> excluded)
V1_MAP = {"XAUUSD": "XAUUSD (PAXG) + XAUUSD_FUT (GC=F)", "XAGUSD": "SILVER (SI=F)", "NAS100": "NAS100 (NQ=F)",
          "US500": "SP500 (ES=F)", "BTC": "BTCUSD", "ETH": "ETHUSD", "SOL": "SOLUSD",
          "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY", "AUDUSD": "AUDUSD", "USDCAD": "USDCAD",
          "USDCHF": "USDCHF", "EURJPY": "EURJPY", "GBPJPY": "GBPJPY"}
ASSETS = list(V1_MAP)
TFS = ("M5", "M15", "H1")
NS_MIN = 60_000_000_000
EXPIRY_D = {"M5": 5, "M15": 10, "H1": 60}        # v1 Yahoo windows: 5m=5d, 15m=10d, 60m=60d
HOLD_CAP_MIN = {"M5": 2 * 1440, "M15": 5 * 1440, "H1": 10 * 1440}
CONFIGS = {"native": ("prox", None), "mid_1h": ("mid", 60), "mid_3h": ("mid", 180)}
COSTS = (1.0, 0.0, 1.5)
TR_DIR = C.CACHE.parent / "v1_backtest" / "trades"; TR_DIR.mkdir(parents=True, exist_ok=True)


def zones_for(sym: str) -> pd.DataFrame:
    A = C.m1_arrays(sym)
    start_ok = (A["index"][0] + pd.Timedelta(days=C.WARMUP_DAYS)).value
    out = []
    for tf in TFS:
        b = C.tf_bars(sym, tf)
        o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        tclose = b["tclose"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        di, oi, sd, al = V.detect_causal(o, h, l, c)
        n_cand = len(di)
        k = al >= 0
        z = pd.DataFrame(dict(sym=sym, tf=tf, side=sd[k].astype(np.int64), disp_i=di[k], ob_i=oi[k], alert_i=al[k],
                              zhi=h[oi[k]], zlo=l[oi[k]], t_ob=b.index.as_unit("ns").asi8[oi[k]],
                              t_alert=tclose[al[k]]))
        z["lag_bars"] = z.alert_i - z.disp_i
        z["t_active"] = z.t_alert + C.DELAY_MIN * NS_MIN
        z = z[(z.t_active >= start_ok) & (z.t_active < C.END.value) & (z.zhi > z.zlo)]
        z.attrs["n_cand"] = n_cand
        out.append(z.assign(n_cand_tf=n_cand))
    z = pd.concat(out, ignore_index=True)
    z["zid"] = np.arange(len(z))
    return z


def _cost_arrays(sym, px, mult):
    sp, cm, sl = zip(*[C.costs(sym, p) for p in px])
    return np.array(sp) * mult / 2.0, np.array(cm) * mult, np.array(sl) * mult


def trades_for(sym: str, A, z: pd.DataFrame) -> pd.DataFrame:
    t = A["t"]; parts = []
    side = z.side.to_numpy(np.int64)
    entry_v1, sl_v1, _ = V.sltp_v1(z.zhi.to_numpy(), z.zlo.to_numpy(), side)
    mid = ((z.zhi + z.zlo) / 2).to_numpy()
    start = np.searchsorted(t, z.t_active.to_numpy(), side="left").astype(np.int64)
    exp_ns = (z.tf.map(EXPIRY_D).to_numpy() * 86400e9).astype(np.int64)
    for cfg, (ent, hold) in CONFIGS.items():
        lvl = entry_v1 if ent == "prox" else mid
        hold_min = z.tf.map(HOLD_CAP_MIN).to_numpy() if hold is None else np.full(len(z), hold)
        risk_plan = np.where(side > 0, lvl - sl_v1, sl_v1 - lvl)
        T = lvl + side * 2.0 * risk_plan
        for mult in COSTS:
            hs, comm, slip = _cost_arrays(sym, lvl, mult)
            f, e, _ = C.find_fill(t, A["o"], A["h"], A["l"], A["c"], start, side, np.ones(len(z), np.int64), lvl, exp_ns, hs)
            ii = np.where(f >= 0)[0]
            if len(ii) == 0: continue
            x, r, w, rk, ep = C.run_exit(t, A["o"], A["h"], A["l"], A["c"], f[ii], side[ii], np.ones(len(ii), np.int64),
                                         e[ii], lvl[ii], sl_v1[ii], T[ii], (hold_min[ii] * NS_MIN).astype(np.int64),
                                         hs[ii], slip[ii], 0, np.full(1, -np.inf), np.full(1, np.inf))
            d = z.iloc[ii][["sym", "tf", "side", "zid", "zhi", "zlo", "lag_bars", "t_active"]].copy()
            d["cfg"] = cfg; d["cost"] = mult; d["level"] = lvl[ii]; d["sl"] = sl_v1[ii]; d["tp_px"] = T[ii]
            d["hold_cap"] = hold_min[ii]
            d["f_i"] = f[ii]; d["x_i"] = x; d["r_gross"] = r; d["why"] = w; d["risk"] = rk; d["epx"] = ep
            d = d[(d.why >= 1) & (d.why <= 4)].copy()
            d["t_fill"] = t[d.f_i.to_numpy()]; d["t_exit"] = t[d.x_i.to_numpy()]
            days = (d.t_exit - d.t_fill) / 86400e9
            d["hold_min"] = (d.t_exit - d.t_fill) / NS_MIN + 1
            comm_d = comm[z.index.get_indexer(d.index)]
            d["r_net"] = d.r_gross - comm_d / d.risk - (C.swap_r(sym, d.side, d.epx, days, d.risk, mult) if mult > 0 else 0.0)
            d["risk_pct"] = d.risk / d.epx
            parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def baseline_for(sym: str, A, tr: pd.DataFrame, draws: int = 3, seed: int = 0) -> pd.DataFrame:
    """Random-entry baseline for every filled trade at cost x1 and x0 (same risk %, TP 2R, same hold cap)."""
    rng = np.random.default_rng(abs(hash(sym)) % (2**32) + seed)
    t = A["t"]; out = []
    x = tr[tr.cost == 1.0]
    for cfg, g in x.groupby("cfg"):
        tf_ = pd.to_datetime(g.t_fill.to_numpy(), utc=True)
        per = tf_.tz_localize(None).to_period("M")
        lo = np.searchsorted(t, per.to_timestamp().tz_localize("UTC").as_unit("ns").asi8)
        hi = np.searchsorted(t, (per + 1).to_timestamp().tz_localize("UTC").as_unit("ns").asi8)
        riskf = g.risk_pct.to_numpy(); hold = g.hold_cap.to_numpy(float)
        for d in range(draws):
            idx = rng.integers(lo, np.maximum(hi, lo + 1))
            idx = np.minimum(idx, len(t) - 2).astype(np.int64)
            side = rng.choice([-1, 1], len(idx)).astype(np.int64)
            for cost in (1.0, 0.0):
                hs, cm, sl = _cost_arrays(sym, A["o"][idx], cost)
                f, e, _ = C.find_fill(t, A["o"], A["h"], A["l"], A["c"], idx, side, np.zeros(len(idx), np.int64),
                                      A["o"][idx], np.zeros(len(idx), np.int64), hs)
                epx = e + side * sl; risk = riskf * epx; S = epx - side * risk; T = epx + side * 2.0 * risk
                xx, r, w, rk, ep = C.run_exit(t, A["o"], A["h"], A["l"], A["c"], f, side, np.zeros(len(idx), np.int64),
                                              e, A["o"][idx], S, T, (hold * NS_MIN).astype(np.int64), hs, sl, 0,
                                              np.full(1, -np.inf), np.full(1, np.inf))
                days = (t[np.maximum(xx, 0)] - t[f]) / 86400e9
                net = r - cm / rk - (C.swap_r(sym, side, ep, days, rk, cost) if cost > 0 else 0)
                ok = (w >= 1) & (w <= 4)
                out.append(pd.DataFrame({"sym": sym, "cfg": cfg, "tf": g.tf.to_numpy()[ok], "t_fill": t[f][ok],
                                         "cost": cost, "draw": d, "r": net[ok]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def run(sym: str) -> str:
    p = TR_DIR / f"{sym}.parquet"
    if p.exists(): return f"{sym} cached"
    t0 = time.time()
    A = C.m1_arrays(sym)
    z = zones_for(sym)
    z.to_parquet(TR_DIR / f"zones_{sym}.parquet")
    tr = trades_for(sym, A, z)
    bl = baseline_for(sym, A, tr)
    bl.to_parquet(TR_DIR / f"baseline_{sym}.parquet")
    tr.to_parquet(p)
    nc = z.groupby("tf").n_cand_tf.first().to_dict()
    return f"{sym} cand={nc} 5star_alerts={z.groupby('tf').size().to_dict()} trades={len(tr)} {time.time()-t0:.0f}s"


if __name__ == "__main__":
    syms = sys.argv[1:]
    if syms == ["all"]: syms = ASSETS
    if len(syms) > 1:
        with Pool(int(os.environ.get("NPROC", "4"))) as pool:
            for msg in pool.imap_unordered(run, syms): print(msg, flush=True)
    else:
        print(run(syms[0]), flush=True)
