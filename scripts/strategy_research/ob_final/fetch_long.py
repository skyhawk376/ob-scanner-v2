"""Fetch longer M1 history for the OB-final study (does NOT overwrite the framework files).
HistData yearly zips 2015..2022 -> data/cache/strategy_research/m1/{ID}_M1_2015_2022.parquet
Binance monthly 2017-08..2022-12 -> data/cache/strategy_research/m1/{SYM}_M1_2017_2022.parquet
Usage: python fetch_long.py histdata [IDs]  |  python fetch_long.py binance
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_histdata as fh, fetch_binance as fb

OUT = fh.OUT

def histdata(ids):
    for i in ids:
        out = OUT / f"{i}_M1_2015_2022.parquet"
        if out.exists():
            print(i, "exists", flush=True); continue
        parts = []
        for y in range(2015, 2023):
            try:
                b = fh.dl(fh.PAIRS[i], y, None)
            except Exception as e:  # network hiccup -> retry once
                print(i, y, "err", e, flush=True)
                p = fh.RAW / fh.PAIRS[i] / f"{y}.zip"
                if p.exists() and p.stat().st_size == 0: p.unlink()
                b = fh.dl(fh.PAIRS[i], y, None)
            if b: parts.append(fh.parse(b))
            else: print(i, y, "missing", flush=True)
        if not parts: continue
        df = pd.concat(parts).sort_index(); df = df[~df.index.duplicated()]
        df.to_parquet(out)
        print(i, len(df), df.index[0], df.index[-1], flush=True)

def binance():
    for s, a in (("BTC", "2017-08"), ("ETH", "2017-08"), ("SOL", "2020-08")):
        out = OUT / f"{s}_M1_2017_2022.parquet"
        if out.exists(): print(s, "exists"); continue
        pair = f"{s}USDT"; parts = []
        for mo in fb.months(a, "2022-12"):
            url = f"https://data.binance.vision/data/spot/monthly/klines/{pair}/1m/{pair}-1m-{mo}.zip"
            c = fb.get(url, fb.RAW / pair / f"{mo}.zip")
            if c: parts.append(fb.parse(c))
            else: print(s, mo, "missing", flush=True)
        df = pd.concat(parts).sort_index(); df = df[~df.index.duplicated()]
        df.to_parquet(out); print(s, len(df), df.index[0], df.index[-1], flush=True)

if __name__ == "__main__":
    if sys.argv[1] == "binance": binance()
    else:
        ids = sys.argv[2:] or ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "USDCHF", "EURJPY", "GBPJPY",
                               "EURGBP", "XAUUSD", "XAGUSD", "US500", "NAS100", "DAX"]
        histdata(ids)
