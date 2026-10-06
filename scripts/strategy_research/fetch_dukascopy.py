"""Download Dukascopy free M1 BID candles (day files) and build per-symbol M1 parquet.

Source: https://datafeed.dukascopy.com/datafeed/{SYM}/{YYYY}/{MM0}/{DD}/BID_candles_min_1.bi5
 (month is 0-indexed; LZMA; records of 24 bytes: int32 t_offset_sec, open, close, low, high (int32 / scale), float32 vol)
Times are UTC. BID only -> spread is modelled separately in costs.

Usage: .venv/bin/python scripts/strategy_research/fetch_dukascopy.py [start YYYY-MM-DD] [end YYYY-MM-DD] [SYM ...]
"""
from __future__ import annotations
import lzma, struct, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np, pandas as pd, requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/cache/strategy_research/duka_raw"
OUT = ROOT / "data/cache/strategy_research/m1"

# our id -> (dukascopy code, price scale)
SYMBOLS = {
    "XAUUSD": ("XAUUSD", 1e3), "XAGUSD": ("XAGUSD", 1e3),
    "EURUSD": ("EURUSD", 1e5), "GBPUSD": ("GBPUSD", 1e5), "USDJPY": ("USDJPY", 1e3),
    "USDCAD": ("USDCAD", 1e5), "AUDUSD": ("AUDUSD", 1e5), "USDCHF": ("USDCHF", 1e5),
    "EURJPY": ("EURJPY", 1e3), "GBPJPY": ("GBPJPY", 1e3), "EURGBP": ("EURGBP", 1e5),
    "US500": ("USA500IDXUSD", 1e3), "NAS100": ("USATECHIDXUSD", 1e3), "DAX": ("DEUIDXEUR", 1e3),
    "WTI": ("LIGHTCMDUSD", 1e3),
}
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"

def fetch_day(sym: str, day: dt.date) -> str:
    code, _ = SYMBOLS[sym]
    p = RAW / sym / f"{day:%Y%m%d}.bi5"
    if p.exists():
        return "cached"
    p.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://datafeed.dukascopy.com/datafeed/{code}/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
    for attempt in range(8):
        try:
            r = S.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(2 + attempt * 3); continue
        if r.status_code == 200:
            p.write_bytes(r.content); return "ok"
        if r.status_code == 404:
            p.write_bytes(b""); return "404"
        time.sleep(3 + attempt * 5)  # 429/5xx backoff
    return "fail"

def decode(sym: str, day: dt.date, b: bytes) -> pd.DataFrame | None:
    if not b:
        return None
    try:
        raw = lzma.decompress(b)
    except Exception:
        return None
    n = len(raw) // 24
    if n == 0:
        return None
    arr = np.frombuffer(raw[: n * 24], dtype=np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"), ("l", ">i4"), ("h", ">i4"), ("v", ">f4")]))
    sc = SYMBOLS[sym][1]
    base = pd.Timestamp(day, tz="UTC")
    df = pd.DataFrame({
        "open": arr["o"] / sc, "high": arr["h"] / sc, "low": arr["l"] / sc, "close": arr["c"] / sc,
        "volume": arr["v"].astype(float)}, index=base + pd.to_timedelta(arr["t"].astype(np.int64), unit="s"))
    return df[df["volume"] > 0]  # Dukascopy pads flat zero-volume minutes when market closed

def build(sym: str, days):
    parts = []
    for d in days:
        p = RAW / sym / f"{d:%Y%m%d}.bi5"
        if p.exists():
            df = decode(sym, d, p.read_bytes())
            if df is not None and len(df):
                parts.append(df)
    if not parts:
        print(sym, "no data"); return
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated()]
    df.index.name = "time"
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{sym}_M1.parquet")
    print(sym, len(df), df.index[0], df.index[-1], "median close", round(df.close.median(), 5), flush=True)

def main():
    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date(2024, 1, 1)
    end = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date(2026, 10, 2)
    syms = sys.argv[3:] or list(SYMBOLS)
    days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() != 5]  # Saturdays empty
    for sym in syms:
        t0 = time.time(); stats = {}
        with ThreadPoolExecutor(4) as ex:
            futs = [ex.submit(fetch_day, sym, d) for d in days]
            for f in as_completed(futs):
                s = f.result(); stats[s] = stats.get(s, 0) + 1
        print(sym, stats, f"{time.time()-t0:.0f}s", flush=True)
        build(sym, days)

if __name__ == "__main__":
    main()
