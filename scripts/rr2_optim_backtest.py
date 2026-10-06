#!/usr/bin/env python3
"""RR-2 optimisation for live strategy "Filtre B" (research only, no deploy).

Filtre B = H1 OB 5★ engine, min 4★, METAUX+FOREX+CRYPTO, virgin OB + FVG,
soft reaction OFF. Live: entry = mid (50% if zone > 1 ATR else OB open),
SL = distal edge + 0.05 ATR, TP = +1R, hold ≈ 1 H1 bar.

Phases
  1. Causal detection (same walk-forward as volume_options_backtest.py) — once,
     cached to data/backtest/rr2_zones.pkl.
  2. Reproduction of the legacy method (simulate_lifecycle, hold≤1 bar,
     timeouts EXCLUDED, tp1 liquidity counts as full reaction) for +1R / +2R.
  3. Grid simulation with explicit trade management and a real time stop
     (exit at close of the last hold bar) under three intrabar models:
       legacy : H1 high/low incl. the touch/fill bar (SL checked first)
       cons   : H1, but on the fill bar TP/+1R only count if the CLOSE is
                beyond the level (the bar's extreme may predate the fill)
       m15    : M15 path (yfinance FX/metals, Binance crypto); fill bar
                handled like cons; falls back to cons when no M15 coverage.

Outputs: data/backtest/summary_rr2_optim.json, rr2_optim_grid.csv,
trades_rr2_<cfg>.csv for headline configs.
"""
from __future__ import annotations

import csv
import itertools
import json
import math
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.cache import read_cache  # noqa: E402
from app.core.lifecycle import (  # noqa: E402
    EXPIRY_BARS,
    MAX_DISTANCE_ATR,
    STATUS_ECHEC,
    STATUS_REACTION,
    simulate_lifecycle,
)
from app.core.symbols import load_instruments  # noqa: E402
from app.engine.detect import detect_zones  # noqa: E402
from app.engine.params import EngineParams, params_for_tf  # noqa: E402
from app.engine.sessions import session_at  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
CACHE = Path("/workspace/ob-scanner-v2/data/cache")
M15_BINANCE = ROOT / "data" / "backtest" / "m15_binance"
OUT = ROOT / "data" / "backtest"
YAML = ROOT / "symbols.yaml"
GROUPS = ["METAUX", "FOREX", "CRYPTO"]
WARM = 80
FILL_CAP_H1 = 24  # limit order must fill within 24 H1 bars after first touch
COST_R = 0.05


# ----------------------------------------------------------------------------
# Phase 1 — detection
# ----------------------------------------------------------------------------
def _utc(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()


def detect_symbol(symbol: str, group: str) -> dict:
    df = read_cache(CACHE, symbol, "H1")
    if df is None or len(df) < WARM + 30:
        return {"symbol": symbol, "group": group, "zones": [], "start": None, "end": None}
    df = _utc(df)
    base = params_for_tf("H1")
    params = EngineParams(**{**base.__dict__, "entry_mode": "mid"})
    seen: set = set()
    zones = []
    for j in range(WARM, len(df)):
        sub = df.iloc[: j + 1]
        for z in detect_zones(sub, symbol=symbol, tf="H1", params=params, min_score=4,
                              require_fresh=True, require_fvg=True):
            key = (z.direction, z.ts_ob)
            if key in seen:
                continue
            seen.add(key)
            zd = z.to_dict()
            zd["det_i"] = len(sub) - 2
            zd["det_ts"] = str(sub.index[len(sub) - 2])
            zd["group"] = group
            zones.append(zd)
    return {"symbol": symbol, "group": group, "zones": zones,
            "start": str(df.index[WARM]), "end": str(df.index[-1])}


def phase1(workers: int = 6) -> dict:
    p = OUT / "rr2_zones.pkl"
    if p.exists():
        return pickle.loads(p.read_bytes())
    ins = [i for i in load_instruments(str(YAML)) if i.group.upper() in GROUPS]
    res = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(detect_symbol, i.id, i.group): i.id for i in ins}
        for f in as_completed(futs):
            r = f.result()
            res[r["symbol"]] = r
    print(f"[phase1] detection {time.time()-t0:.1f}s zones={sum(len(r['zones']) for r in res.values())}")
    p.write_bytes(pickle.dumps(res))
    return res


# ----------------------------------------------------------------------------
# data access
# ----------------------------------------------------------------------------
_H1: dict = {}
_M15: dict = {}


def h1(symbol):
    if symbol not in _H1:
        df = _utc(read_cache(CACHE, symbol, "H1"))
        _H1[symbol] = (df.index, df["open"].to_numpy(float), df["high"].to_numpy(float),
                       df["low"].to_numpy(float), df["close"].to_numpy(float), df)
    return _H1[symbol]


def m15(symbol, group):
    if symbol not in _M15:
        df = None
        if group == "CRYPTO":
            p = M15_BINANCE / f"{symbol}_M15.parquet"
            if p.exists():
                df = pd.read_parquet(p)
        else:
            df = read_cache(CACHE, symbol, "M15")
        if df is None or df.empty:
            _M15[symbol] = None
        else:
            df = _utc(df)
            _M15[symbol] = (df.index, df["open"].to_numpy(float), df["high"].to_numpy(float),
                            df["low"].to_numpy(float), df["close"].to_numpy(float))
    return _M15[symbol]


# ----------------------------------------------------------------------------
# Phase 2 — legacy reproduction (exact old method)
# ----------------------------------------------------------------------------
def legacy_repro(zone: dict, reaction_r: float) -> dict:
    idx, o, h, l, c, df = h1(zone["symbol"])
    life = simulate_lifecycle(df, zone, soft_reaction_r=0.0, reaction_r=reaction_r,
                              require_entry_fill=False)
    r = None
    if life.outcome == STATUS_ECHEC:
        r = -1.0
    elif life.outcome == STATUS_REACTION:
        r = float(life.reaction_threshold_r)
    exit_at = life.reacted_at or life.failed_at
    capped = False
    if life.touched_at and exit_at:
        ti = int(idx.get_indexer([pd.Timestamp(life.touched_at)], method="nearest")[0])
        ei = int(idx.get_indexer([pd.Timestamp(exit_at)], method="nearest")[0])
        if ei - ti > 0:
            capped = True
            r = None
    hit_tp1_first = False
    if life.outcome == STATUS_REACTION and zone.get("tp1") is not None:
        risk = abs(zone["entry"] - zone["sl"])
        rr = abs(zone["tp1"] - zone["entry"]) / risk if risk > 0 else 99
        hit_tp1_first = rr < reaction_r
    return {"r": r, "capped": capped, "touched_at": life.touched_at, "tp1_short": hit_tp1_first}


# ----------------------------------------------------------------------------
# Phase 3 — grid simulation
# ----------------------------------------------------------------------------
def find_touch(zone: dict) -> int | None:
    """Replicates simulate_lifecycle touch / expiry logic. Returns H1 index of first touch."""
    idx, o, h, l, c, _ = h1(zone["symbol"])
    ob_ts = pd.Timestamp(zone["ts_ob"])
    ob_ts = ob_ts.tz_localize("UTC") if ob_ts.tzinfo is None else ob_ts.tz_convert("UTC")
    ob_i = int(idx.searchsorted(ob_ts))
    lo, hi = float(zone["low"]), float(zone["high"])
    atr = float(zone.get("atr") or 0.0) or max(hi - lo, 1e-9)
    mid = (lo + hi) / 2
    lim = EXPIRY_BARS["H1"]
    for i in range(min(ob_i + 3, len(idx)), len(idx)):
        if (i - ob_i) > lim:
            return None
        if atr > 0 and abs(mid - c[i]) / atr > MAX_DISTANCE_ATR:
            return None
        if l[i] <= hi and h[i] >= lo:
            return i
    return None


def levels(zone: dict, entry_mode: str, sl_buf: float) -> tuple[float, float, bool]:
    bull = zone["direction"] == "bull"
    lo, hi, atr = float(zone["low"]), float(zone["high"]), float(zone["atr"])
    height = hi - lo
    if entry_mode in ("mid_live", "mid_live_fill"):
        entry = (lo + hi) / 2 if height > 1.0 * atr else float(zone["open"])
    else:
        d = {"prox": 0.0, "d25": 0.25, "d50": 0.5, "d75": 0.75}[entry_mode]
        entry = hi - d * height if bull else lo + d * height
    sl = lo - sl_buf * atr if bull else hi + sl_buf * atr
    return entry, sl, bull


def manage(bars, k0: int, entry: float, sl: float, bull: bool, tp_r: float,
           n_hold: int, mgmt: str, model: str, fill_first: bool) -> tuple[float | None, str, int]:
    """Walk bars from k0 (fill bar) for n_hold bars. Returns (R, exit_reason, k_exit)."""
    _, o, h, l, c = bars[:5]
    n = len(c)
    risk = abs(entry - sl)
    if risk <= 0:
        return None, "zero_risk", k0
    sgn = 1.0 if bull else -1.0
    tp = entry + sgn * tp_r * risk
    one_r = entry + sgn * 1.0 * risk
    stop = sl
    stop_r = -1.0
    banked = 0.0       # R banked by partial
    size = 1.0          # open fraction
    armed = False       # +1R reached (BE / partial applied)
    for k in range(k0, k0 + n_hold):
        if k >= n:
            return None, "open_eod", k
        hi_, lo_, cl = h[k], l[k], c[k]
        fav = hi_ if bull else lo_
        adv = lo_ if bull else hi_
        first = (k == k0) and fill_first and model != "legacy"
        # 1) stop
        if (adv <= stop) if bull else (adv >= stop):
            return banked + size * stop_r, ("sl" if stop_r < 0 else "be"), k
        # 2) target (on the fill bar only via close for conservative models)
        ref = cl if first else fav
        if (ref >= tp) if bull else (ref <= tp):
            return banked + size * tp_r, "tp", k
        # 3) +1R arm (BE / partial)
        if mgmt != "none" and not armed and ((ref >= one_r) if bull else (ref <= one_r)):
            armed = True
            if mgmt == "partial":
                banked += 0.5 * 1.0
                size = 0.5
            stop, stop_r = entry, 0.0
            # price came back through entry after reaching +1R inside this bar
            if (cl <= entry) if bull else (cl >= entry):
                return banked + size * 0.0, "be", k
    k = k0 + n_hold - 1
    cl = c[k]
    return banked + size * (sgn * (cl - entry) / risk), "time", k


def sim_zone(zone: dict, touch_i: int, cfg: dict, model: str) -> dict | None:
    """Simulate one zone under cfg; returns trade dict or None if never filled."""
    entry, sl, bull = levels(zone, cfg["entry"], cfg["sl_buf"])
    touch_mode = cfg["entry"] == "mid_live"  # live legacy: managed from first zone contact
    sym, grp = zone["symbol"], zone["group"]
    H = h1(sym)
    idx = H[0]
    used = model
    if model == "m15":
        M = m15(sym, grp)
        t_touch = idx[touch_i]
        if M is None or t_touch < M[0][0] or t_touch > M[0][-1]:
            used = "cons_fallback"
        else:
            midx, mo, mh, ml, mc = M
            s = int(midx.searchsorted(t_touch))
            lo, hi = float(zone["low"]), float(zone["high"])
            cap = s + FILL_CAP_H1 * 4 + 4
            f = None
            for k in range(s, min(cap, len(mc))):
                if touch_mode:
                    if ml[k] <= hi and mh[k] >= lo:
                        f = k
                        break
                else:
                    if (ml[k] <= entry) if bull else (mh[k] >= entry):
                        f = k
                        break
            if f is None:
                return None
            # hold N hours from the fill M15 bar open
            end_t = midx[f] + pd.Timedelta(hours=cfg["hold"])
            n_hold = int(midx.searchsorted(end_t)) - f
            r, why, ke = manage((midx, mo, mh, ml, mc), f, entry, sl, bull, cfg["tp_r"],
                                max(n_hold, 1), cfg["mgmt"], "m15", True)
            if why == "open_eod" and ke >= len(mc) and midx[-1] < H[0][-1]:
                used = "cons_fallback"  # M15 ran out before H1 end → use H1
            else:
                return _trade(zone, cfg, entry, sl, r, why, midx[f], "m15")
    # H1 models
    _, o, h, l, c, _df = H
    f = None
    if touch_mode:
        f = touch_i
    else:
        for k in range(touch_i, min(touch_i + FILL_CAP_H1 + 1, len(c))):
            if (l[k] <= entry) if bull else (h[k] >= entry):
                f = k
                break
    if f is None:
        return None
    m = "legacy" if model == "legacy" else "cons"
    r, why, _ = manage((idx, o, h, l, c), f, entry, sl, bull, cfg["tp_r"], cfg["hold"],
                       cfg["mgmt"], m, True)
    return _trade(zone, cfg, entry, sl, r, why, idx[f], used)


def _trade(zone, cfg, entry, sl, r, why, t_fill, used):
    atr = float(zone["atr"]) or 1e-9
    return {
        "risk_atr": round(abs(entry - sl) / atr, 4),
        "symbol": zone["symbol"], "group": zone["group"], "direction": zone["direction"],
        "ts_ob": zone["ts_ob"], "score": int(zone["score"]), "entry": entry, "sl": sl,
        "fill_at": str(t_fill), "fill_session": session_at(t_fill) or "",
        "r": None if r is None else round(float(r), 4), "exit": why, "model_used": used,
    }


# ----------------------------------------------------------------------------
# metrics
# ----------------------------------------------------------------------------
COST_ATR = 0.02  # alt. cost model: 0.02 H1-ATR per round trip, in R = 0.02 / (risk/ATR)


def metrics(trades: list[dict], wd: dict[str, float], cost: float = 0.0, cost_atr: float = 0.0) -> dict:
    closed = [t for t in trades if t["r"] is not None]
    closed.sort(key=lambda t: t["fill_at"])
    rs = [t["r"] - cost - (cost_atr / max(t["risk_atr"], 1e-6) if cost_atr else 0.0) for t in closed]
    n = len(rs)
    tpw = sum(sum(1 for t in closed if t["group"] == g) / wd[g] for g in wd if wd[g] > 0)
    out = {"n": n, "open": len(trades) - n, "tpw": tpw}
    if not n:
        out.update(wr=None, avg_r=None, sum_r=0.0, pf=None, max_dd=None, max_lstreak=0, obj=0.0)
        return out
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    eq = peak = dd = 0.0
    streak = mx = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        if r < 0:
            streak += 1
            mx = max(mx, streak)
        elif r > 0:
            streak = 0
    gl = -sum(losses)
    out.update(
        wr=len(wins) / n, avg_r=sum(rs) / n, sum_r=sum(rs),
        pf=(sum(wins) / gl) if gl > 0 else float("inf"),
        max_dd=dd, max_lstreak=mx, obj=(sum(rs) / n) * tpw,
        exits={k: sum(1 for t in closed if t["exit"] == k) for k in sorted({t["exit"] for t in closed})},
    )
    return out


# ----------------------------------------------------------------------------
def main() -> int:
    t0 = time.time()
    det = phase1()
    # effective windows per group (all symbols warmed up, up to common end)
    win = {}
    for g in GROUPS:
        rs = [r for r in det.values() if r["group"] == g and r["start"]]
        a = max(pd.Timestamp(r["start"]) for r in rs)
        b = min(pd.Timestamp(r["end"]) for r in rs)
        win[g] = (a, b)
    wd_full = {g: (b - a).total_seconds() / 86400 * 5 / 7 for g, (a, b) in win.items()}
    split = {g: a + (b - a) / 2 for g, (a, b) in win.items()}
    wd_half = {g: v / 2 for g, v in wd_full.items()}
    print("[windows]", {g: (str(a), str(b), round(wd_full[g], 1)) for g, (a, b) in win.items()})

    zones = [z for r in det.values() for z in r["zones"]]
    for z in zones:
        z["symbol"] = z["symbol"]
    # touches
    for z in zones:
        z["touch_i"] = find_touch(z)
    # ----- Phase 2 reproduction -----
    repro = {}
    for rr in (1.0, 2.0):
        rows = []
        for z in zones:
            lr = legacy_repro(z, rr)
            rows.append(lr)
        closed = [x for x in rows if x["r"] is not None]
        rs = [x["r"] for x in closed]
        ta = [pd.Timestamp(x["touched_at"]) for x in closed]
        span = (max(ta) - min(ta)).total_seconds() / 86400
        # in-window closed (drop touches before group window start)
        inwin = []
        for z, x in zip(zones, rows):
            if x["r"] is None:
                continue
            t = pd.Timestamp(x["touched_at"])
            if win[z["group"]][0] <= t <= win[z["group"]][1]:
                inwin.append((z["group"], x["r"]))
        tpw_win = sum(sum(1 for g, _ in inwin if g == gg) / wd_full[gg] for gg in GROUPS)
        repro[f"{rr:.0f}R"] = {
            "signals": len(rows), "closed": len(closed),
            "wins": sum(1 for r in rs if r > 0), "losses": sum(1 for r in rs if r <= 0),
            "wr": sum(1 for r in rs if r > 0) / len(rs), "avg_r": sum(rs) / len(rs), "sum_r": sum(rs),
            "hold_capped_excluded": sum(1 for x in rows if x["capped"]),
            "tp1_liquidity_below_target_credited_full": sum(1 for x in closed if x["tp1_short"] and x["r"] > 0),
            "touch_span_days_old": span,
            "tpw_old_convention": len(closed) / (span * 5 / 7),
            "closed_in_window": len(inwin),
            "tpw_corrected": tpw_win,
        }
        print(f"[repro {rr}R]", repro[f"{rr:.0f}R"])

    # zones eligible: touched inside group window, touch after detection bar
    elig = []
    viol = 0
    for z in zones:
        ti = z["touch_i"]
        if ti is None:
            continue
        idx = h1(z["symbol"])[0]
        t = idx[ti]
        a, b = win[z["group"]]
        if not (a <= t <= b):
            continue
        if ti <= z["det_i"]:
            viol += 1
            continue
        elig.append(z)
    print(f"[eligible] zones touched in window: {len(elig)} (touch<=det violations dropped: {viol})")

    # ----- grid -----
    grid = []
    for entry, sl_buf, hold, stars, sess, mgmt, tp_r in itertools.product(
        ["mid_live", "mid_live_fill", "prox", "d25", "d50", "d75"],
        [0.05, 0.10, 0.25],
        [1, 2, 3, 4],
        [4, 5],
        ["all", "lonny"],
        ["none", "be", "partial"],
        [1.0, 2.0],
    ):
        if tp_r == 1.0 and mgmt != "none":
            continue
        grid.append(dict(entry=entry, sl_buf=sl_buf, hold=hold, stars=stars, sess=sess,
                         mgmt=mgmt, tp_r=tp_r))
    models = ["legacy", "cons", "m15"]
    rows = []
    store = {}
    for cfg in grid:
        name = (f"{cfg['entry']}|sl{cfg['sl_buf']}|h{cfg['hold']}|s{cfg['stars']}|{cfg['sess']}"
                f"|{cfg['mgmt']}|{cfg['tp_r']:.0f}R")
        for model in models:
            trades = []
            for z in elig:
                if int(z["score"]) < cfg["stars"]:
                    continue
                tr = sim_zone(z, z["touch_i"], cfg, model)
                if tr is None:
                    continue
                if cfg["sess"] == "lonny" and tr["fill_session"] not in ("London", "NY"):
                    continue
                trades.append(tr)
            full = metrics(trades, wd_full)
            net = metrics(trades, wd_full, COST_R)
            neta = metrics(trades, wd_full, 0.0, COST_ATR)
            closed = [t for t in trades if t["r"] is not None]
            is_ = [t for t in closed if pd.Timestamp(t["fill_at"]) < split[t["group"]]]
            oos = [t for t in closed if pd.Timestamp(t["fill_at"]) >= split[t["group"]]]
            mi, mo = metrics(is_, wd_half), metrics(oos, wd_half)
            byg = {g: metrics([t for t in closed if t["group"] == g], {g: wd_full[g]}) for g in GROUPS}
            row = {"config": name, "model": model, **cfg,
                   **{k: full[k] for k in ("n", "open", "tpw", "wr", "avg_r", "sum_r", "pf", "max_dd", "max_lstreak", "obj")},
                   "avg_r_net": net["avg_r"], "sum_r_net": net["sum_r"], "pf_net": net["pf"], "obj_net": net["obj"],
                   "avg_r_net_atr": neta["avg_r"], "sd_r": (float(np.std([t["r"] for t in closed], ddof=1)) if len(closed) > 1 else None),
                   "med_risk_atr": (float(np.median([t["risk_atr"] for t in closed])) if closed else None),
                   "is_n": mi["n"], "is_avg_r": mi["avg_r"], "is_wr": mi["wr"], "is_tpw": mi["tpw"],
                   "oos_n": mo["n"], "oos_avg_r": mo["avg_r"], "oos_wr": mo["wr"], "oos_tpw": mo["tpw"],
                   "fallback_n": sum(1 for t in closed if t["model_used"] == "cons_fallback"),
                   "exits": json.dumps(full.get("exits", {})),
                   **{f"{g}_n": byg[g]["n"] for g in GROUPS},
                   **{f"{g}_avg_r": byg[g]["avg_r"] for g in GROUPS},
                   **{f"{g}_wr": byg[g]["wr"] for g in GROUPS}}
            rows.append(row)
            store[(name, model)] = trades
    print(f"[grid] {len(grid)} configs x {len(models)} models in {time.time()-t0:.1f}s")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "rr2_optim_grid.csv", index=False)
    pickle.dump(store, open(OUT / "rr2_trades_store.pkl", "wb"))
    payload = {
        "generated_at": datetime.now(tz=PARIS).isoformat(),
        "windows": {g: [str(a), str(b), wd_full[g]] for g, (a, b) in win.items()},
        "split": {g: str(s) for g, s in split.items()},
        "eligible_zones": len(elig),
        "touch_le_det_dropped": viol,
        "fill_cap_h1": FILL_CAP_H1,
        "cost_r": COST_R,
        "cost_atr": COST_ATR,
        "repro_legacy": repro,
        "n_configs": len(grid),
        "models": models,
    }
    (OUT / "rr2_optim_meta.json").write_text(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
