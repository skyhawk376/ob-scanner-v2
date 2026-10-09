#!/usr/bin/env python3
"""Sanity backtest of the v3 « Kasper » rules on cached M1 history (NOT an optimisation).

Uses the exact live engine (app.v3.detect + app.v3.sim): M1 bars from
data/cache/strategy_research/m1 resampled to M5…W; each zone TF uses its lower TF for the
reversal trigger and trade management (M5 zones -> M1). Costs: app.v3.costs (same spread/
commission/slippage model as scripts/strategy_research/common.py, extended).

  /tmp/obv/bin/python scripts/v3/backtest.py --start 2025-10-01 --end 2026-09-30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.v3 import params as P  # noqa: E402
from app.v3.detect import detect_zones  # noqa: E402
from app.v3.sim import simulate_zone  # noqa: E402

M1 = ROOT / "data/cache/strategy_research/m1"
GROUPS = {"XAUUSD": "METAUX", "XAGUSD": "METAUX", "EURUSD": "FOREX", "GBPUSD": "FOREX",
          "USDJPY": "FOREX", "USDCAD": "FOREX", "AUDUSD": "FOREX", "USDCHF": "FOREX",
          "EURJPY": "FOREX", "GBPJPY": "FOREX", "EURGBP": "FOREX", "BTC": "CRYPTO",
          "ETH": "CRYPTO", "SOL": "CRYPTO", "NAS100": "NQ100"}
RULE = {"M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h", "D": "1D", "W": "W-MON"}


def resample(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "M1":
        return m1
    kw = {"label": "left", "closed": "left"}
    if tf == "W":
        r = m1.resample("W-MON", label="left", closed="left")
    else:
        r = m1.resample(RULE[tf], **kw)
    return r.agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--symbols", default=",".join(GROUPS))
    ap.add_argument("--tfs", default="M5,M15,M30,H1,H4,D,W")
    ap.add_argument("--out", default=str(ROOT / "data/backtest/v3_sanity"))
    a = ap.parse_args()
    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sym in a.symbols.split(","):
        t0 = time.time()
        warm = pd.Timedelta(days=400)  # W/D need history for ATR / pivots
        m1 = pd.read_parquet(M1 / f"{sym}_M1.parquet")[["open", "high", "low", "close"]].astype(float)
        m1.index = pd.DatetimeIndex(m1.index).tz_convert("UTC").as_unit("ns")
        m1 = m1[(m1.index >= start - warm) & (m1.index < end)]
        bars = {tf: resample(m1, tf) for tf in ["M5", "M15", "M30", "H1", "H4", "D", "W"]}
        bars["M1"] = m1[m1.index >= start - pd.Timedelta(days=10)]
        for tf in a.tfs.split(","):
            htf = bars[tf]
            if tf in ("M5", "M15", "M30"):
                htf = htf[htf.index >= start - pd.Timedelta(days=20)]
            ltf = bars[P.LOWER_TF[tf]]
            zs = [z for z in detect_zones(htf, tf, sym, GROUPS[sym]) if pd.Timestamp(z["ts_ob"]) >= start]
            for z in zs:
                r = simulate_zone(z, htf, ltf)
                tr = r["trade"]
                rows.append({
                    "symbol": sym, "group": GROUPS[sym], "tf": tf, "dir": z["direction"],
                    "ts_ob": z["ts_ob"], "state": r["state"], "n_touch": r["n_touch"],
                    "touch_score": max([t["score"] for t in r["touches"]], default=None),
                    "alert_touch": any(e["kind"] == "touch" for e in r["events"]),
                    "entry_ts": tr["entry_ts"] if tr else None,
                    "trigger": tr["trigger"] if tr else None,
                    "exit": tr["exit"] if tr else None,
                    "r_gross": tr["r_gross"] if tr else None,
                    "r_net": tr["r_net"] if tr else None,
                    "risk_atr": (tr["risk"] / z["atr"]) if tr else None,
                    "be": bool(tr and tr["be_ts"]),
                })
        print(f"{sym} done {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "zones.csv", index=False)
    tr = df[df.exit.notna()]
    days = np.busday_count(start.date(), end.date())

    def summ(g):
        return {"n": int(len(g)), "wr_tp": round(float((g.exit == "tp").mean()), 3) if len(g) else None,
                "sl": int((g.exit == "sl").sum()), "be": int((g.exit == "be_exit").sum()),
                "avg_r_gross": round(float(g.r_gross.mean()), 3) if len(g) else None,
                "avg_r_net": round(float(g.r_net.mean()), 3) if len(g) else None,
                "sum_r_net": round(float(g.r_net.sum()), 1), "per_day": round(len(g) / days, 2)}

    rep = {"period": [a.start, a.end], "weekdays": int(days), "zones": int(len(df)),
           "zones_alerted_touch": int(df.alert_touch.sum()),
           "touch_alerts_per_day": round(float(df.alert_touch.sum()) / days, 2),
           "all": summ(tr),
           "by_tf": {k: summ(g) for k, g in tr.groupby("tf")},
           "by_group": {k: summ(g) for k, g in tr.groupby("group")},
           "by_trigger": {k: summ(g) for k, g in tr.groupby("trigger")}}
    (out / "summary.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(json.dumps(rep, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
