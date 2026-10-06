"""Download Binance spot M1 klines from data.binance.vision monthly zips (+ daily zips for the current month).
Output: data/cache/strategy_research/m1/{SYM}_M1.parquet (UTC index, open/high/low/close/volume).
Usage: .venv/bin/python scripts/strategy_research/fetch_binance.py 2023-01 2026-09 BTC ETH SOL PAXG
"""
from __future__ import annotations
import io, sys, zipfile, datetime as dt
from pathlib import Path
import pandas as pd, requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/cache/strategy_research/binance_raw"
OUT = ROOT / "data/cache/strategy_research/m1"

def months(a, b):
    y, m = map(int, a.split("-")); y2, m2 = map(int, b.split("-"))
    while (y, m) <= (y2, m2):
        yield f"{y}-{m:02d}"; m += 1
        if m == 13: y, m = y + 1, 1

def get(url, path):
    if path.exists():
        return path.read_bytes() or None
    r = requests.get(url, timeout=60)
    path.parent.mkdir(parents=True, exist_ok=True)
    if r.status_code != 200:
        path.write_bytes(b""); return None
    path.write_bytes(r.content); return r.content

def parse(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6))
    df.columns = ["t", "open", "high", "low", "close", "volume"]
    t = df["t"].astype("int64")
    t = t.where(t < 10**14, t // 1000)  # 2025+ files are in microseconds
    df.index = pd.to_datetime(t, unit="ms", utc=True)
    df.index.name = "time"
    return df.drop(columns="t")

def main():
    a, b, syms = sys.argv[1], sys.argv[2], sys.argv[3:]
    for s in syms:
        pair = f"{s}USDT"; parts = []
        for mo in months(a, b):
            url = f"https://data.binance.vision/data/spot/monthly/klines/{pair}/1m/{pair}-1m-{mo}.zip"
            c = get(url, RAW / pair / f"{mo}.zip")
            if c:
                parts.append(parse(c))
            else:
                print(s, mo, "missing monthly -> trying daily", flush=True)
                y, m = map(int, mo.split("-"))
                d = dt.date(y, m, 1)
                while d.month == m and d < dt.date.today():
                    url = f"https://data.binance.vision/data/spot/daily/klines/{pair}/1m/{pair}-1m-{d}.zip"
                    c = get(url, RAW / pair / f"{d}.zip")
                    if c: parts.append(parse(c))
                    d += dt.timedelta(1)
        df = pd.concat(parts).sort_index(); df = df[~df.index.duplicated()]
        OUT.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUT / f"{s}_M1.parquet")
        print(s, len(df), df.index[0], df.index[-1], flush=True)

if __name__ == "__main__":
    main()
