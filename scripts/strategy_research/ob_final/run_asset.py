"""Per-asset simulation of all pre-registered OB-final families (A/C zone-limit entries, B LTF-confirmation entries),
all holds/TPs/management modes/cost multipliers. Checkpoint = one parquet per asset in data/cache/.../ob_final/trades/.
Usage: python run_asset.py SYM [SYM ...]   (or 'all' -> multiprocessing pool)
"""
from __future__ import annotations
import sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
import core as C

TR_DIR = C.CACHE / "trades"; TR_DIR.mkdir(exist_ok=True)
NS_MIN = 60_000_000_000
EXPIRY_D = {"H1": 5, "H4": 15, "D1": 40}
PIVN = {"H1": 3, "H4": 3, "D1": 2}
HOLDS = {"H1": {"3h": 180, "1d": 1440, "2d": 2880},
         "H4": {"3h": 180, "1d": 1440, "2d": 2880, "5d": 7200, "10d": 14400},
         "D1": {"3h": 180, "5d": 7200, "10d": 14400}}
COSTS = (1.0, 1.5, 0.0)
MGMT = (0, 1, 2, 3)

def _cost_arrays(sym, px, mult):
    sp, cm, sl = zip(*[C.costs(sym, p) for p in px])
    return np.array(sp) * mult / 2.0, np.array(cm) * mult, np.array(sl) * mult

def _finish(sym, base: pd.DataFrame, A, f, x, r, w, rk, ep, mult, comm):
    d = base.copy()
    d["x_i"] = x; d["r_gross"] = r; d["why"] = w; d["risk"] = rk; d["epx"] = ep
    d = d[(w >= 1) & (w <= 4)].copy()
    t = A["t"]
    d["t_fill"] = t[d["f_i"].to_numpy()]; d["t_exit"] = t[d["x_i"].to_numpy()]
    days = (d["t_exit"] - d["t_fill"]) / (86400 * 1e9)
    d["hold_min"] = ((d["t_exit"] - d["t_fill"]) / NS_MIN + 1).astype(np.float32)
    d["r_net"] = d["r_gross"] - comm[d.index.to_numpy()] / d["risk"] - (
        C.swap_r(sym, d["side"], d["epx"], days, d["risk"], mult) if mult > 0 else 0.0)
    d["cost"] = np.float32(mult)
    return d

def zone_trades(sym, A, zones: pd.DataFrame, trail: dict) -> list[pd.DataFrame]:
    out = []
    if zones.empty: return out
    t = A["t"]
    reqs = []
    for entry in ("prox", "mid"):
        z = zones.copy(); z["entry"] = entry
        bull = z.side > 0
        z["level"] = np.where(entry == "prox", np.where(bull, z.zhi, z.zlo), (z.zlo + z.zhi) / 2)
        z["sl"] = np.where(bull, z.zlo - 0.2 * z.atr, z.zhi + 0.2 * z.atr)
        reqs.append(z)
    R = pd.concat(reqs, ignore_index=True)
    start = np.searchsorted(t, R["t_active"].to_numpy(), side="left").astype(np.int64)
    exp_ns = (R["tf"].map(EXPIRY_D).to_numpy() * 86400 * 1e9).astype(np.int64)
    side = R["side"].to_numpy(np.int64); lvl = R["level"].to_numpy(float); slv = R["sl"].to_numpy(float)
    risk_plan = np.where(side > 0, lvl - slv, slv - lvl)
    for mult in COSTS:
        hs, comm, slip = _cost_arrays(sym, lvl, mult)
        f, e, ext = C.find_fill(t, A["o"], A["h"], A["l"], A["c"], start, side, np.ones(len(R), np.int64), lvl, exp_ns, hs)
        filled = np.where(f >= 0)[0]
        if len(filled) == 0: continue
        liq = np.where(side > 0, np.fmax(R["liq_pre"].to_numpy(), ext), np.fmin(R["liq_pre"].to_numpy(), ext))
        liq_rr = np.where(side > 0, liq - lvl, lvl - liq) / risk_plan
        for tpn in ("2R", "3R", "LIQ"):
            if tpn == "LIQ":
                ok = filled[liq_rr[filled] >= 1.5]; T = liq
            else:
                rr = float(tpn[0]); ok = filled; T = lvl + side * rr * risk_plan
            for tf in R["tf"].unique():
                sel_tf = ok[R["tf"].to_numpy()[ok] == tf]
                if len(sel_tf) == 0: continue
                tl, th = trail[tf]
                for hn, hmin in HOLDS[tf].items():
                    for mg in MGMT:
                        ii = sel_tf
                        x, r, w, rk, ep = C.run_exit(t, A["o"], A["h"], A["l"], A["c"], f[ii], side[ii],
                                                     np.ones(len(ii), np.int64), e[ii], lvl[ii], slv[ii], T[ii],
                                                     np.full(len(ii), hmin * NS_MIN, np.int64), hs[ii], slip[ii],
                                                     mg, tl, th)
                        base = R.iloc[ii][["sym", "tf", "side", "zid", "entry", "fvg", "score4", "tr20", "tr50"]].copy()
                        base.index = ii
                        base["f_i"] = f[ii]; base["tp"] = tpn; base["hold"] = hn; base["mgmt"] = np.int8(mg)
                        base["fam"] = "Z"; base["tp_px"] = T[ii]
                        out.append(_finish(sym, base, A, f, x, r, w, rk, ep, mult, comm))
    return out

def ltf_signals(sym, A, zones, ltf_b: pd.DataFrame, W_h: dict) -> pd.DataFrame:
    """Family B: tap of HTF zone then LTF CHoCH. Returns one signal row per zone (if any)."""
    t = A["t"]; h1m = A["h"]; l1m = A["l"]
    o_ns = ltf_b.index.as_unit("ns").asi8
    tc = ltf_b["tclose"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    lh = ltf_b.high.to_numpy(); ll = ltf_b.low.to_numpy(); lc = ltf_b.close.to_numpy(); la = ltf_b.atr.to_numpy()
    is_ph, is_pl = C.pivots(lh, ll, 2)
    ar = np.arange(len(lh))
    last_ph = np.maximum.accumulate(np.where(is_ph, ar, -1)); last_pl = np.maximum.accumulate(np.where(is_pl, ar, -1))
    last_ph = np.concatenate([[-1, -1], last_ph[:-2]]); last_pl = np.concatenate([[-1, -1], last_pl[:-2]])  # confirmed p+2<=b
    rows = []
    for z in zones.itertuples(index=False):
        s = np.searchsorted(t, z.t_active)
        e_end = np.searchsorted(t, z.t_active + EXPIRY_D[z.tf] * 86400 * 10**9)
        if s >= e_end: continue
        if z.side > 0: hit = np.nonzero(l1m[s:e_end] <= z.zhi)[0]
        else: hit = np.nonzero(h1m[s:e_end] >= z.zlo)[0]
        if len(hit) == 0: continue
        tap_i = s + hit[0]; t_tap = t[tap_i]
        b0 = np.searchsorted(o_ns, t_tap, side="right") - 1
        wend = t_tap + W_h[z.tf] * 3600 * 10**9
        ext = ll[b0] if z.side > 0 else lh[b0]
        sig = -1
        b = b0
        while b < len(lc) and tc[b] <= wend:
            if z.side > 0:
                ext = min(ext, ll[b])
                if lc[b] < z.zlo: break
                p = last_ph[b]
                if p >= b0 - 24 and p >= 0 and lc[b] > lh[p]: sig = b; break
            else:
                ext = max(ext, lh[b])
                if lc[b] > z.zhi: break
                p = last_pl[b]
                if p >= b0 - 24 and p >= 0 and lc[b] < ll[p]: sig = b; break
            b += 1
        if sig < 0: continue
        t_ent = tc[sig] + C.DELAY_MIN * NS_MIN
        ei = np.searchsorted(t, t_ent)
        if ei >= len(t): continue
        # HTF leg extreme known at signal (liq_pre + M1 extreme from zone live to entry)
        liq = max(z.liq_pre, h1m[s:ei].max()) if z.side > 0 else min(z.liq_pre, l1m[s:ei].min())
        sl_ltf = ext - 0.1 * la[sig] if z.side > 0 else ext + 0.1 * la[sig]
        sl_zone = z.zlo - 0.2 * z.atr if z.side > 0 else z.zhi + 0.2 * z.atr
        rows.append(dict(zid=z.zid, ei=ei, sl_ltf=sl_ltf, sl_zone=sl_zone, liq=liq, t_tap=t_tap))
    return pd.DataFrame(rows)

def ltf_trades(sym, A, zones, sigs: pd.DataFrame, ltf: str, trail_ltf, trail_htf) -> list[pd.DataFrame]:
    out = []
    if sigs.empty: return out
    t = A["t"]
    S = sigs.merge(zones[["zid", "sym", "tf", "side", "fvg", "score4", "tr20", "tr50"]], on="zid")
    side = S["side"].to_numpy(np.int64); ei = S["ei"].to_numpy(np.int64)
    px = A["o"][ei]
    for mult in COSTS:
        hs, comm, slip = _cost_arrays(sym, px, mult)
        f, e, _ = C.find_fill(t, A["o"], A["h"], A["l"], A["c"], ei, side, np.zeros(len(S), np.int64), px,
                              np.zeros(len(S), np.int64), hs)
        epx = e + side * slip
        for sln in ("ltf", "zone"):
            slv = S[f"sl_{sln}"].to_numpy(float)
            risk = np.where(side > 0, epx - slv, slv - epx)
            valid = risk > 0
            for tpn in ("3R", "5R", "LIQ"):
                if tpn == "LIQ":
                    T = S["liq"].to_numpy(float); rr = np.where(valid, side * (T - epx) / np.where(valid, risk, 1), 0)
                    ok = np.where(valid & (rr >= 2.0))[0]
                else:
                    T = epx + side * float(tpn[0]) * risk; ok = np.where(valid)[0]
                if len(ok) == 0: continue
                for hn, hmin in (("2d", 2880), ("3h", 180)):
                    for mg in MGMT:
                        tl, th = trail_ltf  # prereg: LTF structure trail for family B
                        x, r, w, rk, ep = C.run_exit(t, A["o"], A["h"], A["l"], A["c"], f[ok], side[ok],
                                                     np.zeros(len(ok), np.int64), e[ok], px[ok], slv[ok], T[ok],
                                                     np.full(len(ok), hmin * NS_MIN, np.int64), hs[ok], slip[ok], mg, tl, th)
                        base = S.iloc[ok][["sym", "tf", "side", "zid", "fvg", "score4", "tr20", "tr50"]].copy()
                        base.index = ok
                        base["entry"] = f"ltf_{ltf}_{sln}"; base["f_i"] = f[ok]; base["tp"] = tpn; base["hold"] = hn
                        base["mgmt"] = np.int8(mg); base["fam"] = "B"; base["tp_px"] = T[ok]
                        out.append(_finish(sym, base, A, f, x, r, w, rk, ep, mult, comm))
    return out

def run(sym: str):
    p = TR_DIR / f"{sym}.parquet"
    if p.exists(): return f"{sym} cached"
    t0 = time.time()
    A = C.m1_arrays(sym)
    start_ok = A["index"][0] + pd.Timedelta(days=C.WARMUP_DAYS)
    tfs = ["H1", "H4", "D1"] if sym in C.INDICES else ["H4", "D1"]
    d1 = C.tf_bars(sym, "D1")
    bars = {tf: (d1 if tf == "D1" else C.tf_bars(sym, tf)) for tf in tfs}
    zl = []
    for tf in tfs:
        z = C.detect_obx(bars[tf], PIVN[tf], sym, tf)
        if z.empty: continue
        z = z[(z.t_active >= start_ok.value) & (z.t_active < C.END.value)]
        zl.append(z)
    zones = pd.concat(zl, ignore_index=True)
    # one zone per OB candle: a later BOS re-using the same OB candle would duplicate the same order -> keep the first
    zones = zones.sort_values("t_active").drop_duplicates(["tf", "side", "ob_i"], keep="first").reset_index(drop=True)
    zones["zid"] = np.arange(len(zones))
    ta = zones["t_active"].to_numpy()
    zones["tr20"] = C.d1_trend(d1, ta, "ema20"); zones["tr50"] = C.d1_trend(d1, ta, "ema50")
    zones.to_parquet(C.CACHE / f"zones_{sym}.parquet")
    trail = {tf: C.trail_arrays(sym, bars[tf]) for tf in tfs}
    parts = zone_trades(sym, A, zones, trail)
    hz = zones[zones.tf.isin(["H4", "D1"])]
    for ltf in ("M5", "M15"):
        lb = C.tf_bars(sym, ltf)
        sigs = ltf_signals(sym, A, hz, lb, {"H4": 24, "D1": 48})
        tl = C.trail_arrays(sym, lb)
        parts += [d.assign(ltf=ltf) for d in ltf_trades(sym, A, hz, sigs, ltf, tl, None)]
        del lb
    df = pd.concat(parts, ignore_index=True)
    keep = ["sym", "tf", "side", "zid", "entry", "fvg", "score4", "tr20", "tr50", "tp", "hold", "mgmt", "fam", "cost",
            "t_fill", "t_exit", "hold_min", "r_gross", "r_net", "risk", "epx", "why", "tp_px"]
    df = df[keep]
    for col in ("sym", "tf", "entry", "tp", "hold", "fam"): df[col] = df[col].astype("category")
    for col in ("r_gross", "r_net"): df[col] = df[col].astype(np.float32)
    df.to_parquet(p)
    return f"{sym} zones={len(zones)} rows={len(df)} {time.time()-t0:.0f}s"

if __name__ == "__main__":
    syms = sys.argv[1:]
    if syms == ["all"]:
        syms = C.ASSETS
    if len(syms) > 1:
        with Pool(int(__import__("os").environ.get("NPROC", "4"))) as pool:
            for msg in pool.imap_unordered(run, syms):
                print(msg, flush=True)
    else:
        print(run(syms[0]), flush=True)
