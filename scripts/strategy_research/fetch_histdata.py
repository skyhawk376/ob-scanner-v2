"""Download free HistData.com M1 ASCII bars (forex, metals, indices, WTI).
Timestamps in the files are EST *without* DST (fixed UTC-5) -> converted to UTC.
Past years = one yearly zip; current year = monthly zips.
Output: data/cache/strategy_research/m1/{ID}_M1.parquet
Usage: .venv/bin/python scripts/strategy_research/fetch_histdata.py 2023 2026 9 [ID ...]
"""
from __future__ import annotations
import io, re, sys, time, zipfile
from pathlib import Path
import pandas as pd, requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/cache/strategy_research/histdata_raw"
OUT = ROOT / "data/cache/strategy_research/m1"
# our id -> histdata pair code
PAIRS = {"XAUUSD": "xauusd", "XAGUSD": "xagusd", "EURUSD": "eurusd", "GBPUSD": "gbpusd", "USDJPY": "usdjpy",
         "USDCAD": "usdcad", "AUDUSD": "audusd", "USDCHF": "usdchf", "EURJPY": "eurjpy", "GBPJPY": "gbpjpy",
         "EURGBP": "eurgbp", "US500": "spxusd", "NAS100": "nsxusd", "DAX": "grxeur", "WTI": "wtiusd"}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"

def dl(pair: str, year: int, month: int | None) -> bytes | None:
    tag = f"{year}" if month is None else f"{year}{month:02d}"
    p = RAW / pair / f"{tag}.zip"
    if p.exists():
        return p.read_bytes() or None
    page = f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{year}" + ("" if month is None else f"/{month}")
    h = S.get(page, timeout=60).text
    m = re.search(r'name="tk" id="tk" value="([^"]+)"', h)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not m:
        p.write_bytes(b""); return None
    dm = f"{year}" if month is None else f"{year}{month:02d}"
    r = S.post("https://www.histdata.com/get.php", data=dict(tk=m.group(1), date=str(year), datemonth=dm, platform="ASCII", timeframe="M1", fxpair=pair.upper()), headers={"Referer": page}, timeout=120)
    time.sleep(1.0)
    ok = r.status_code == 200 and r.content[:2] == b"PK"
    p.write_bytes(r.content if ok else b"")
    return r.content if ok else None

def parse(b: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(b))
    name = [n for n in z.namelist() if n.endswith(".csv")][0]
    df = pd.read_csv(z.open(name), sep=";", header=None, names=["t", "open", "high", "low", "close", "volume"])
    t = pd.to_datetime(df["t"], format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)
    df.index = t.dt.tz_localize("UTC"); df.index.name = "time"
    return df.drop(columns="t")

def main():
    y0, y1, last_month = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    ids = sys.argv[4:] or list(PAIRS)
    for i in ids:
        pair = PAIRS[i]; parts = []
        for y in range(y0, y1 + 1):
            if y < y1:
                b = dl(pair, y, None)
                if b: parts.append(parse(b))
                else: print(i, y, "missing", flush=True)
            else:
                for mo in range(1, last_month + 1):
                    b = dl(pair, y, mo)
                    if b: parts.append(parse(b))
                    else: print(i, y, mo, "missing", flush=True)
        df = pd.concat(parts).sort_index(); df = df[~df.index.duplicated()]
        OUT.mkdir(parents=True, exist_ok=True); df.to_parquet(OUT / f"{i}_M1.parquet")
        print(i, len(df), df.index[0], df.index[-1], "median", round(df.close.median(), 5), flush=True)

if __name__ == "__main__":
    main()
