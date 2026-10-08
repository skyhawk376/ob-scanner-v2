#!/usr/bin/env python3
"""Prod touched zones (all TFs) + shape features + outcomes + Telegram 'alerted' flag.

Inputs (read-only copies, never committed):
  /workspace/ob_shape/prod/zones_api.json     GET /zones?statuses=reaction,echec,touchee&limit=5000
  /workspace/ob_shape/prod/cache/*.parquet    prod candle cache (flyctl ssh sftp snapshot)
  /workspace/ob_shape/prod/results/telegram_dryrun.log   (dry_run=false lines = really sent)
Fallback candles when the prod cache does not cover the OB: research M1 (14 symbols) resampled.
Output: scripts/ob_shape/results/prod_zones.csv
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "strategy_research"))
sys.path.insert(0, str(ROOT / "tradingview"))
from features import compute_features, fill_outcome, strict_pivots, textbook_flags  # noqa: E402
from pine_reference import epoch_seconds, pine_atr  # noqa: E402

PROD = Path("/workspace/ob_shape/prod")
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
TFMAP = {"D1": "D", "W1": "W"}
RULE = {"M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}


def utc(df):
    df = df.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()[["open", "high", "low", "close"]].astype(float)


_cache: dict = {}


def candles(sym: str, tf: str, src: str):
    key = (sym, tf, src)
    if key in _cache:
        return _cache[key]
    df = None
    if src == "prod":
        p = PROD / "cache" / f"{sym}_{tf}.parquet"
        if p.exists():
            df = utc(pd.read_parquet(p))
    else:
        import common as C
        if sym in C.GROUP and tf in RULE:
            df = C.resample(sym, RULE[tf])
    _cache[key] = df
    return df


def parse_alerts():
    rows = []
    for line in open(PROD / "results" / "telegram_dryrun.log"):
        d = json.loads(line)
        if d.get("dry_run"):
            continue
        lines = d["text"].split("\n")
        if len(lines) < 3 or not lines[1].startswith("ZONE "):
            continue
        ev = lines[0]
        ev = "contact" if "Premier contact" in ev else "reaction" if "Réaction" in ev else "sl" if "Invalidation" in ev else "other"
        m = re.match(r"ZONE (ACHAT|VENTE) (\S+) (\S+)", lines[1])
        lo_s, hi_s = re.findall(r"[\d.]+", lines[2])[:2]
        rows.append(dict(ts=d["ts"], event=ev, direction="bull" if m.group(1) == "ACHAT" else "bear",
                         symbol=m.group(2), tf=TFMAP.get(m.group(3), m.group(3)), lo_s=lo_s, hi_s=hi_s))
    return pd.DataFrame(rows)


def _tol(s: str) -> float:
    dec = len(s.split(".")[1]) if "." in s else 0
    return 0.51 * 10 ** (-dec)


def main():
    zs = pd.DataFrame(json.load(open(PROD / "zones_api.json"))["zones"])
    al = parse_alerts()
    al.to_csv(OUT / "prod_alerts_sent.csv", index=False)
    rows = []
    for _, z in zs.iterrows():
        sym, tf, bull = z.symbol, z.tf, z.direction == "bull"
        N = 2 if tf in ("D", "W") else 3
        r = {k: z[k] for k in ("id", "symbol", "tf", "direction", "ts_ob", "ts_bos", "touched_at", "status",
                               "low", "high", "entry", "sl", "tp2", "atr", "score", "trend", "sweep",
                               "session_label", "touched_session", "mfe_r", "mae_r",
                               "trade_status", "trade_r", "trade_exit", "trade_model", "trade_fill_at",
                               "bias_h4", "bias_d1", "aligned_h4d1")}
        r.update(s1=int(z.star1_fvg), s2=int(z.star2_trend), s3=int(z.star3_fib), s4=int(z.star4_liquidity),
                 s5=int(bool(z.star5_session)), group=None)
        # alerted (really sent to Telegram, any event)
        m = al[(al.symbol == sym) & (al.tf == tf) & (al.direction == z.direction)]
        m = m[[abs(float(a) - z.low) <= _tol(a) and abs(float(b) - z.high) <= _tol(b) for a, b in zip(m.lo_s, m.hi_s)]] if len(m) else m
        r["alerted"] = int(len(m) > 0)
        r["alert_events"] = ",".join(sorted(set(m.event))) if len(m) else ""
        r["alert_msgs"] = len(m)
        t_ob = pd.Timestamp(z.ts_ob).tz_convert("UTC")
        t_bos = pd.Timestamp(z.ts_bos).tz_convert("UTC")
        t_touch = pd.Timestamp(z.touched_at).tz_convert("UTC") if z.touched_at else None
        r["src"] = None
        for src in ("prod", "research"):
            df = candles(sym, tf, src)
            if df is None or t_ob not in df.index or t_bos not in df.index:
                continue
            ob = df.index.get_loc(t_ob)
            if ob < 30:
                continue
            j = df.index.get_loc(t_bos)
            touch = int(df.index.searchsorted(t_touch)) if t_touch is not None else None
            if touch is None or touch >= len(df):
                continue
            o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
            t = epoch_seconds(df.index)
            ph, pl = strict_pivots(h, l, N)
            piv = [p for p in (ph if bull else pl) if p[0] < j]
            if not piv:
                continue
            piv_i, piv_p = piv[-1]
            seg = l[piv_i:j + 1] if bull else h[piv_i:j + 1]
            k = piv_i + int(np.argmin(seg) if bull else np.argmax(seg))
            ob_exp = next((x for x in range(k, -1, -1) if ((c[x] < o[x]) if bull else (c[x] > o[x]))), -1)
            r["src"] = src
            r["ob_recomputed_match"] = int(ob_exp == ob)
            r["ob_price_match"] = int(abs(h[ob] - z.high) <= 1e-6 * abs(z.high) + 1e-12 and abs(l[ob] - z.low) <= 1e-6 * abs(z.low) + 1e-12)
            r["broke_level_ok"] = int((c[j] > piv_p) if bull else (c[j] < piv_p))
            r["fvg_ok_recomputed"] = int((h[ob] < l[ob + 2]) if bull else (l[ob] > h[ob + 2]))
            r["virgin_ok"] = int(not np.any((l[ob + 3:touch] <= z.high) & (h[ob + 3:touch] >= z.low)))
            f = compute_features(o, h, l, c, t, ob=ob, j=j, k=k, piv_i=piv_i, piv_p=piv_p, touch=touch, bull=bull,
                                 top=z.high, bot=z.low, entry=z.entry, sl=z.sl, atr=z.atr,
                                 pivots_opp=pl if bull else ph, N=N)
            hold, hb, _ = fill_outcome(o, h, l, c, touch=touch, bull=bull, entry=z.entry, sl=z.sl)
            r.update(f)
            r.update(textbook_flags(f))
            r.update(hold=hold, hold_bars=hb, ob_i=ob, bos_i=j, leg_i=k, touch_i=touch, piv_i=piv_i, piv_p=piv_p)
            break
        rows.append(r)
    d = pd.DataFrame(rows)
    # group from symbols.yaml
    import yaml
    y = yaml.safe_load(open(ROOT / "symbols.yaml"))
    gmap = {}
    for g, items in y.items():
        if isinstance(items, list):
            for it in items:
                gmap[it if isinstance(it, str) else it.get("id")] = g
    d["group"] = d.symbol.map(gmap)
    d["risk_pct"] = (d.entry - d.sl).abs() / d.entry * 100
    d.to_csv(OUT / "prod_zones.csv", index=False)
    print(len(d), "prod touched zones;", d.src.value_counts(dropna=False).to_dict())
    print("alerted:", int(d.alerted.sum()))
    print(d.groupby("tf").agg(n=("id", "size"), feat=("src", lambda s: s.notna().sum()),
                              ob_match=("ob_recomputed_match", "mean"), px=("ob_price_match", "mean")))


if __name__ == "__main__":
    main()
