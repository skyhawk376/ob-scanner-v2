#!/usr/bin/env python3
"""Fetch Binance spot 15m klines for CRYPTO symbols over the H1 cache window.

Research helper for RR2 optimisation (M15 intrabar path). Writes parquet to
data/backtest/m15_binance/<SYM>_M15.parquet (does NOT touch the shared cache).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.cache import read_cache  # noqa: E402
from app.core.symbols import load_instruments  # noqa: E402

CACHE = Path("/workspace/ob-scanner-v2/data/cache")
OUT = ROOT / "data" / "backtest" / "m15_binance"


def fetch(sym: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = []
    cur = start_ms
    while cur < end_ms:
        url = (
            "https://api.binance.com/api/v3/klines?symbol="
            f"{sym}&interval=15m&limit=1000&startTime={cur}&endTime={end_ms}"
        )
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        if not data:
            break
        rows.extend(data)
        cur = int(data[-1][0]) + 15 * 60 * 1000
        time.sleep(0.15)
    df = pd.DataFrame(
        [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in rows],
        columns=["ts", "open", "high", "low", "close", "volume"],
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop_duplicates("ts").set_index("ts").sort_index()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ins = [i for i in load_instruments(str(ROOT / "symbols.yaml")) if i.group == "CRYPTO"]
    for i in ins:
        h1 = read_cache(CACHE, i.id, "H1")
        if h1 is None or h1.empty:
            continue
        a = int(h1.index.min().value // 10**6)
        b = int((h1.index.max() + pd.Timedelta(hours=1)).value // 10**6)
        sym = f"{i.id}USDT"
        try:
            df = fetch(sym, a, b)
        except Exception as e:  # noqa: BLE001
            print(f"{i.id}: FAIL {e}")
            continue
        df.to_parquet(OUT / f"{i.id}_M15.parquet")
        agg = df.resample("1h").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        j = h1.join(agg, rsuffix="_m", how="inner")
        rel = ((j.close - j.close_m).abs() / j.close).median() * 100
        print(f"{i.id}: {len(df)} bars {df.index.min()} -> {df.index.max()} | H1 match n={len(j)} med|dclose|%={rel:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
