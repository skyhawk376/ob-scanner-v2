#!/usr/bin/env python3
"""Multi-timeframe momentum alignment filter on top of live "Filtre B" (research only).

Baseline B (live): H1 OB engine, min 4★, METAUX+FOREX+CRYPTO, virgin OB + FVG,
entry mid, SL distal + 0.05 ATR, TP +1R (and +2R test), hold 1h, soft OFF.

Trade simulation = the REALISTIC simulator of scripts/rr2_optim_backtest.py
(imported, not modified): the mid limit must actually fill (≤24 H1 bars after
the first touch), M15 price path (yfinance FX/metals, Binance crypto), every trade
closed by TP / SL / 1h time stop. Zones come from the same causal detection cache
(data/backtest/rr2_zones.pkl), same group windows, same IS/OOS split.

Filter: per-TF bias at the OB TOUCH time T (open of the H1 touch bar). Only bars
fully closed at T are used (bar available at open + duration; D1 at next 00:00 UTC).
TFs: M15 (cache / Binance), H1 (H1 cache + M15-resampled history), H4 (resampled
from that H1), D1 (yfinance daily, fetched once to data/backtest/momentum_d1/).
Bias definitions:
  struct  : last 2 confirmed fractal pivots (n=3): HH+HL bull / LH+LL bear / else neutral
  ema50   : last close vs EMA50
  ema2050 : EMA20 vs EMA50
Bias needs ≥50 closed bars (EMA) / 2+2 pivots (struct), else neutral.

Outputs: data/backtest/momentum_trades.csv, momentum_filter_variants.csv,
summary_momentum_filter.json, MOMENTUM_FILTER.md (repo root).
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import rr2_optim_backtest as rr  # noqa: E402  (realistic simulator, read-only reuse)
from app.core.cache import read_cache  # noqa: E402
from app.core.symbols import load_instruments  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
OUT = ROOT / "data" / "backtest"
D1_DIR = OUT / "momentum_d1"
TFS = ["M15", "H1", "H4", "D1"]
DEFS = ["struct", "ema50", "ema2050"]
PIVOT_N = 3
STALE = {"M15": pd.Timedelta(days=4), "H1": pd.Timedelta(days=4),
         "H4": pd.Timedelta(days=4), "D1": pd.Timedelta(days=6)}
YF_OVERRIDE = {"TON": "TON11419-USD", "SUI": "SUI20947-USD"}
SEED = 7


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------
def fetch_d1(instruments) -> dict[str, str]:
    import yfinance as yf

    status = {}
    for ins in instruments:
        p = D1_DIR / f"{ins.id}_D1.csv"
        if p.exists():
            status[ins.id] = "cached"
            continue
        tick = YF_OVERRIDE.get(ins.id, ins.yf)
        try:
            d = yf.Ticker(tick).history(start="2025-06-01", end="2026-10-06", interval="1d",
                                        auto_adjust=False)
        except Exception as e:  # pragma: no cover
            status[ins.id] = f"error {e}"
            continue
        if d is None or d.empty:
            status[ins.id] = "empty"
            continue
        out = pd.DataFrame({
            "date": [ts.date().isoformat() for ts in d.index],  # local label date
            "open": d["Open"].values, "high": d["High"].values,
            "low": d["Low"].values, "close": d["Close"].values,
        })
        out.to_csv(p, index=False)
        status[ins.id] = f"fetched {tick} {len(out)}"
    return status


def _ohlc_resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    kw = {"origin": "epoch"} if rule.endswith("h") else {}
    return df.resample(rule, label="left", closed="left", **kw).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def build_tf_series(symbol: str, group: str) -> dict:
    """Return {tf: (open_ts, avail_ts, high, low, close)} for available TFs."""
    out = {}
    # M15 (same source as the simulator path)
    M = rr.m15(symbol, group)
    if M is not None:
        midx, mo, mh, ml, mc = M
        out["M15"] = (midx, midx + pd.Timedelta(minutes=15), mh, ml, mc)
    # H1 = H1 cache, earlier history from cache M15 resampled
    h1 = rr._utc(read_cache(rr.CACHE, symbol, "H1"))[["open", "high", "low", "close"]]
    m15c = read_cache(rr.CACHE, symbol, "M15")
    if m15c is not None and not m15c.empty:
        r = _ohlc_resample(rr._utc(m15c)[["open", "high", "low", "close"]], "1h")
        r = r[r.index < h1.index[0]]
        h1 = pd.concat([r, h1]).sort_index()
        h1 = h1[~h1.index.duplicated(keep="last")]
    out["H1"] = (h1.index, h1.index + pd.Timedelta(hours=1), h1["high"].to_numpy(float),
                 h1["low"].to_numpy(float), h1["close"].to_numpy(float))
    h4 = _ohlc_resample(h1, "4h")
    out["H4"] = (h4.index, h4.index + pd.Timedelta(hours=4), h4["high"].to_numpy(float),
                 h4["low"].to_numpy(float), h4["close"].to_numpy(float))
    p = D1_DIR / f"{symbol}_D1.csv"
    if p.exists():
        d = pd.read_csv(p).dropna()
        if len(d):
            dates = pd.to_datetime(d["date"]).dt.tz_localize("UTC")
            idx = pd.DatetimeIndex(dates)
            out["D1"] = (idx, idx + pd.Timedelta(days=1), d["high"].to_numpy(float),
                         d["low"].to_numpy(float), d["close"].to_numpy(float))
    if "D1" not in out:  # fallback: UTC days resampled from the H1 history (e.g. TON)
        d1 = _ohlc_resample(h1, "1D")
        out["D1"] = (d1.index, d1.index + pd.Timedelta(days=1), d1["high"].to_numpy(float),
                     d1["low"].to_numpy(float), d1["close"].to_numpy(float))
    return out


def _ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def bias_arrays(h, l, c) -> dict[str, np.ndarray]:
    n = len(c)
    e20, e50 = _ema(c, 20), _ema(c, 50)
    warm = np.arange(n) >= 49
    ema50 = np.where(warm, np.sign(c - e50), 0).astype(int)
    ema2050 = np.where(warm, np.sign(e20 - e50), 0).astype(int)
    # structure: pivot at i confirmed at bar i+N (closed)
    ph, pl = [], []
    for i in range(PIVOT_N, n - PIVOT_N):
        wh, wl = h[i - PIVOT_N:i + PIVOT_N + 1], l[i - PIVOT_N:i + PIVOT_N + 1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1:
            ph.append((i + PIVOT_N, h[i]))
        if l[i] == wl.min() and (wl == l[i]).sum() == 1:
            pl.append((i + PIVOT_N, l[i]))
    st = np.zeros(n, dtype=int)
    a = b = 0
    hs: list[float] = []
    ls: list[float] = []
    for k in range(n):
        while a < len(ph) and ph[a][0] <= k:
            hs.append(ph[a][1]); a += 1
        while b < len(pl) and pl[b][0] <= k:
            ls.append(pl[b][1]); b += 1
        if len(hs) >= 2 and len(ls) >= 2:
            if hs[-1] > hs[-2] and ls[-1] > ls[-2]:
                st[k] = 1
            elif hs[-1] < hs[-2] and ls[-1] < ls[-2]:
                st[k] = -1
    return {"struct": st, "ema50": ema50, "ema2050": ema2050}


def biases_at(series: dict, cache: dict, T: pd.Timestamp) -> dict:
    res = {}
    for tf in TFS:
        if tf not in series:
            for d in DEFS:
                res[f"{d}_{tf}"] = None
            continue
        idx, avail, h, l, c = series[tf]
        if tf not in cache:
            cache[tf] = bias_arrays(h, l, c)
        k = int(np.searchsorted(avail.asi8, T.value, side="right")) - 1
        ok = k >= 0 and (T - avail[k]) <= STALE[tf]
        for d in DEFS:
            res[f"{d}_{tf}"] = int(cache[tf][d][k]) if ok else None
    return res


# ----------------------------------------------------------------------------
# variants
# ----------------------------------------------------------------------------
def aligned(t: dict, d: str, tfs: list[str], mode: str = "all") -> bool:
    sgn = 1 if t["direction"] == "bull" else -1
    vals = [t[f"{d}_{tf}"] for tf in tfs if t.get(f"{d}_{tf}") is not None]
    if not vals:
        return False
    n_al = sum(1 for v in vals if v == sgn)
    if mode == "all":
        return n_al == len(vals)
    if mode == "nm1":
        return n_al >= len(vals) - 1
    if mode == "noopp":
        return all(v != -sgn for v in vals)
    raise ValueError(mode)


VARIANTS = [
    ("D1", ["D1"], "all"),
    ("H4", ["H4"], "all"),
    ("H4+D1", ["H4", "D1"], "all"),
    ("H1+H4+D1", ["H1", "H4", "D1"], "all"),
    ("ALL(M15+H1+H4+D1)", TFS, "all"),
    ("ALL>=N-1", TFS, "nm1"),
    ("H4+D1 no-opposite", ["H4", "D1"], "noopp"),
]


def boot_ci(rs, n_boot=4000, seed=SEED):
    if len(rs) < 2:
        return (None, None)
    rng = np.random.default_rng(seed)
    a = np.asarray(rs, float)
    m = rng.choice(a, size=(n_boot, len(a)), replace=True).mean(axis=1)
    return (float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975)))


def perm_p(sel, rej, n_perm=4000, seed=SEED):
    """One-sided p-value that mean(sel) - mean(rej) >= observed under random labels."""
    if not sel or not rej:
        return None
    rng = np.random.default_rng(seed)
    a = np.asarray(sel + rej, float)
    k = len(sel)
    obs = np.mean(sel) - np.mean(rej)
    cnt = 0
    for _ in range(n_perm):
        rng.shuffle(a)
        if a[:k].mean() - a[k:].mean() >= obs - 1e-12:
            cnt += 1
    return cnt / n_perm


def evaluate(trades, wd_full, wd_half, split, label, extra=None, rej=None):
    m = rr.metrics(trades, wd_full)
    closed = [t for t in trades if t["r"] is not None]
    is_ = [t for t in closed if pd.Timestamp(t["fill_at"]) < split[t["group"]]]
    oos = [t for t in closed if pd.Timestamp(t["fill_at"]) >= split[t["group"]]]
    mi, mo = rr.metrics(is_, wd_half), rr.metrics(oos, wd_half)
    lo, hi = boot_ci([t["r"] for t in closed])
    row = {"variant": label, **(extra or {}),
           "n": m["n"], "tpw": m["tpw"], "wr": m["wr"], "avg_r": m["avg_r"], "sum_r": m["sum_r"],
           "pf": m["pf"], "max_dd": m["max_dd"], "max_lstreak": m["max_lstreak"],
           "ci_lo": lo, "ci_hi": hi,
           "is_n": mi["n"], "is_avg_r": mi["avg_r"], "is_wr": mi["wr"],
           "oos_n": mo["n"], "oos_avg_r": mo["avg_r"], "oos_wr": mo["wr"],
           "both_halves_pos": bool(mi["avg_r"] is not None and mo["avg_r"] is not None
                                   and mi["avg_r"] > 0 and mo["avg_r"] > 0),
           "exits": json.dumps(m.get("exits", {})),
           "low_n": m["n"] < 40}
    for g in rr.GROUPS:
        mg = rr.metrics([t for t in closed if t["group"] == g], {g: wd_full[g]})
        row[f"{g}_n"], row[f"{g}_wr"], row[f"{g}_avg_r"] = mg["n"], mg["wr"], mg["avg_r"]
    if rej is not None:
        rc = [t["r"] for t in rej if t["r"] is not None]
        row["rej_n"] = len(rc)
        row["rej_avg_r"] = float(np.mean(rc)) if rc else None
        row["rej_wr"] = (sum(1 for r in rc if r > 0) / len(rc)) if rc else None
        row["perm_p"] = perm_p([t["r"] for t in closed], rc)
    # selection score (RR2 rule): worst-half avg R x volume; n<40 penalised to -inf
    w = min(x for x in (mi["avg_r"], mo["avg_r"]) if x is not None) if (mi["avg_r"] is not None and mo["avg_r"] is not None) else None
    row["score"] = (w * m["tpw"]) if (w is not None and m["n"] >= 40) else float("-inf")
    return row


# ----------------------------------------------------------------------------
def main() -> int:
    t0 = time.time()
    ins = [i for i in load_instruments(str(rr.YAML)) if i.group.upper() in rr.GROUPS]
    d1_status = fetch_d1(ins)
    det = rr.phase1()
    win = {}
    for g in rr.GROUPS:
        rs_ = [r for r in det.values() if r["group"] == g and r["start"]]
        win[g] = (max(pd.Timestamp(r["start"]) for r in rs_), min(pd.Timestamp(r["end"]) for r in rs_))
    wd_full = {g: (b - a).total_seconds() / 86400 * 5 / 7 for g, (a, b) in win.items()}
    split = {g: a + (b - a) / 2 for g, (a, b) in win.items()}
    wd_half = {g: v / 2 for g, v in wd_full.items()}

    zones = [z for r in det.values() for z in r["zones"]]
    for z in zones:
        z["touch_i"] = rr.find_touch(z)
    elig = []
    for z in zones:
        ti = z["touch_i"]
        if ti is None:
            continue
        t = rr.h1(z["symbol"])[0][ti]
        a, b = win[z["group"]]
        if a <= t <= b and ti > z["det_i"]:
            elig.append(z)
    print(f"[momentum] eligible zones {len(elig)}")

    # --- biases at touch (and at fill, sensitivity) ---
    series_cache, bias_cache = {}, {}
    tf_avail = {}
    for z in elig:
        s = z["symbol"]
        if s not in series_cache:
            series_cache[s] = build_tf_series(s, z["group"])
            bias_cache[s] = {}
            tf_avail[s] = sorted(series_cache[s].keys(), key=TFS.index)
        T = rr.h1(s)[0][z["touch_i"]]
        z["touch_at"] = str(T)
        z["bias"] = biases_at(series_cache[s], bias_cache[s], T)

    # --- simulate (realistic + old-method reference) ---
    cfgs = {
        "1R": dict(entry="mid_live_fill", sl_buf=0.05, hold=1, stars=4, sess="all", mgmt="none", tp_r=1.0),
        "2R": dict(entry="mid_live_fill", sl_buf=0.05, hold=1, stars=4, sess="all", mgmt="none", tp_r=2.0),
    }
    trades = {k: [] for k in cfgs}
    for k, cfg in cfgs.items():
        for z in elig:
            tr = rr.sim_zone(z, z["touch_i"], cfg, "m15")
            if tr is None:
                continue
            tr.update({"touch_at": z["touch_at"], **z["bias"]})
            # fill-time biases (sensitivity)
            Tf = pd.Timestamp(tr["fill_at"])
            fb = biases_at(series_cache[z["symbol"]], bias_cache[z["symbol"]], Tf)
            tr.update({f"fill_{kk}": v for kk, v in fb.items()})
            trades[k].append(tr)
    # old method reference (legacy_repro, all zones like the old reports)
    legacy = {}
    for rrv in (1.0, 2.0):
        rows = []
        for z in zones:
            lr = rr.legacy_repro(z, rrv)
            if lr["r"] is None:
                continue
            ti = z.get("touch_i")
            T = pd.Timestamp(lr["touched_at"])
            s = z["symbol"]
            if s not in series_cache:
                series_cache[s] = build_tf_series(s, z["group"])
                bias_cache[s] = {}
            rows.append({"group": z["group"], "direction": z["direction"], "r": lr["r"],
                         "touched_at": str(T), **biases_at(series_cache[s], bias_cache[s], T)})
        legacy[f"{rrv:.0f}R"] = rows

    # TF coverage over the 48-symbol universe (M15 = simulator source; stale = ends before window)
    missing_m15, d1_fallback = [], []
    for i in ins:
        M = rr.m15(i.id, i.group)
        if M is None or M[0][-1] < win[i.group][0]:
            missing_m15.append(i.id)
        if not (D1_DIR / f"{i.id}_D1.csv").exists():
            d1_fallback.append(i.id)
    missing_d1 = d1_fallback

    # --- variants ---
    rows = []
    store = {}
    for k in ("1R", "2R"):
        base = trades[k]
        rows.append(evaluate(base, wd_full, wd_half, split, "B baseline",
                             {"tp": k, "bias_def": "-", "tfs": "-", "timing": "touch"}))
        store[(k, "base", "-")] = base
        for d in DEFS:
            for name, tfs, mode in VARIANTS:
                sel = [t for t in base if aligned(t, d, tfs, mode)]
                rej = [t for t in base if not aligned(t, d, tfs, mode)]
                rows.append(evaluate(sel, wd_full, wd_half, split, f"B + {name}",
                                     {"tp": k, "bias_def": d, "tfs": name, "timing": "touch"}, rej))
                store[(k, name, d)] = sel
            # counter-momentum check (all TFs against)
            opp = [t for t in base if aligned({**t, "direction": "bear" if t["direction"] == "bull" else "bull"}, d, ["H4", "D1"], "all")]
            rows.append(evaluate(opp, wd_full, wd_half, split, "B + H4+D1 AGAINST (control)",
                                 {"tp": k, "bias_def": d, "tfs": "H4+D1 against", "timing": "touch"}))
    var = pd.DataFrame(rows)

    # best momentum variant (selection rule fixed: n>=40, rank by worst-half avgR x tpw, at +1R)
    mom = var[(var.tfs != "-") & (~var.tfs.str.contains("against")) & (var.tp == "1R")]
    best1 = mom.sort_values("score", ascending=False).iloc[0]
    best_key = (best1["tfs"], best1["bias_def"])
    mom2 = var[(var.tfs != "-") & (~var.tfs.str.contains("against")) & (var.tp == "2R")]
    best2 = mom2.sort_values("score", ascending=False).iloc[0]

    # fill-time sensitivity for best variants
    sens = []
    for (tfs_name, d) in {best_key, (best2["tfs"], best2["bias_def"])}:
        spec = next(v for v in VARIANTS if v[0] == tfs_name)
        for k in ("1R", "2R"):
            sel = [t for t in trades[k] if aligned({**t, **{kk[5:]: v for kk, v in t.items() if kk.startswith("fill_")}}, d, spec[1], spec[2])]
            sens.append(evaluate(sel, wd_full, wd_half, split, f"B + {tfs_name} @fill",
                                 {"tp": k, "bias_def": d, "tfs": tfs_name, "timing": "fill"}))
    sens = pd.DataFrame(sens)

    # old method numbers for baseline + best variant (reference only)
    old = []
    for k, rows_ in legacy.items():
        for label, d, spec in [("B baseline (old method)", None, None),
                               (f"B + {best_key[0]} [{best_key[1]}] (old method)", best_key[1],
                                next(v for v in VARIANTS if v[0] == best_key[0]))]:
            sel = rows_ if spec is None else [t for t in rows_ if aligned(t, d, spec[1], spec[2])]
            rs_ = [t["r"] for t in sel]
            inwin = [t for t in sel if win[t["group"]][0] <= pd.Timestamp(t["touched_at"]) <= win[t["group"]][1]]
            tpw = sum(sum(1 for t in inwin if t["group"] == g) / wd_full[g] for g in rr.GROUPS)
            gl = -sum(r for r in rs_ if r < 0)
            old.append({"variant": label, "tp": k, "n": len(rs_),
                        "wr": (sum(1 for r in rs_ if r > 0) / len(rs_)) if rs_ else None,
                        "avg_r": (sum(rs_) / len(rs_)) if rs_ else None,
                        "pf": (sum(r for r in rs_ if r > 0) / gl) if gl > 0 else None,
                        "tpw_corrected": tpw})
    old = pd.DataFrame(old)

    # EMA-length neighbour check (close vs EMA_span) on D1 and H4+D1 — robustness, not selection
    ema_sens = []
    for span in (20, 30, 50, 100, 200):
        for k in ("1R", "2R"):
            for name, tfs in (("D1", ["D1"]), ("H4+D1", ["H4", "D1"])):
                sel, rej = [], []
                for t in trades[k]:
                    ser = series_cache[t["symbol"]]
                    T = pd.Timestamp(t["touch_at"])
                    sgn = 1 if t["direction"] == "bull" else -1
                    ok = True
                    for tf in tfs:
                        idx, avail, h, l, c = ser[tf]
                        kk = int(np.searchsorted(avail.asi8, T.value, side="right")) - 1
                        if kk < span - 1 or (T - avail[kk]) > STALE[tf]:
                            continue  # TF not warm/available → skipped
                        e = _ema(c[: kk + 1], span)[-1]
                        if np.sign(c[kk] - e) != sgn:
                            ok = False
                    (sel if ok else rej).append(t)
                ema_sens.append(evaluate(sel, wd_full, wd_half, split, f"B + {name} close>EMA{span}",
                                         {"tp": k, "bias_def": f"ema{span}", "tfs": name, "timing": "touch"}, rej))
    ema_sens = pd.DataFrame(ema_sens)
    ema_sens.to_csv(OUT / "momentum_filter_ema_length_check.csv", index=False)

    # bias coverage stats
    cov = {}
    base1 = trades["1R"]
    for d in DEFS:
        for tf in TFS:
            vals = [t[f"{d}_{tf}"] for t in base1]
            cov[f"{d}_{tf}"] = {"missing": sum(v is None for v in vals),
                                "bull": sum(v == 1 for v in vals), "bear": sum(v == -1 for v in vals),
                                "neutral": sum(v == 0 for v in vals)}

    # --- save ---
    OUT.mkdir(parents=True, exist_ok=True)
    tr_rows = []
    for k in ("1R", "2R"):
        for t in trades[k]:
            tr_rows.append({"tp": k, **t})
    with (OUT / "momentum_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(tr_rows[0].keys()))
        w.writeheader()
        w.writerows(tr_rows)
    var.to_csv(OUT / "momentum_filter_variants.csv", index=False)
    sens.to_csv(OUT / "momentum_filter_fill_sensitivity.csv", index=False)
    payload = {
        "generated_at": datetime.now(tz=PARIS).isoformat(),
        "simulator": "scripts/rr2_optim_backtest.py sim_zone(model='m15', entry='mid_live_fill', sl_buf=0.05, hold=1, mgmt='none')",
        "windows": {g: [str(a), str(b), wd_full[g]] for g, (a, b) in win.items()},
        "split": {g: str(s) for g, s in split.items()},
        "eligible_zones": len(elig),
        "tfs": TFS, "bias_defs": DEFS, "pivot_n": PIVOT_N,
        "missing_m15_symbols": missing_m15, "d1_resampled_from_h1_symbols": missing_d1,
        "d1_fetch": d1_status,
        "bias_coverage_1R": cov,
        "best_1R": best1.to_dict(), "best_2R": best2.to_dict(),
        "variants": var.to_dict(orient="records"),
        "fill_sensitivity": sens.to_dict(orient="records"),
        "old_method_reference": old.to_dict(orient="records"),
        "ema_length_check": ema_sens.to_dict(orient="records"),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT / "summary_momentum_filter.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"[momentum] done {time.time()-t0:.1f}s best1R={best_key} best2R={(best2['tfs'], best2['bias_def'])}")
    pd.set_option("display.width", 250)
    cols = ["tp", "bias_def", "tfs", "n", "tpw", "wr", "avg_r", "pf", "max_dd", "max_lstreak",
            "is_avg_r", "oos_avg_r", "rej_n", "rej_avg_r", "perm_p", "score"]
    print(var[cols].round(3).to_string())
    print(sens[cols[:12]].round(3).to_string())
    print(old.round(3).to_string())
    print(ema_sens[cols].round(3).to_string())
    print(json.dumps({"missing_m15": missing_m15, "missing_d1": missing_d1}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
