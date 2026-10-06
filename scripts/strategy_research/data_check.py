"""Data inventory + quality checks: coverage, weekday gaps, timezone cross-check vs Dukascopy (UTC) sample days."""
from __future__ import annotations
import json, sys, warnings, datetime as dt
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ALL, GROUP, M1_DIR, OUT, ROOT, load_m1  # noqa: E402
from fetch_dukascopy import RAW as DUKA_RAW, decode  # noqa: E402

rows = []
for s in ALL:
    df = load_m1(s)
    idx = df.index
    wk = idx[idx.dayofweek < 5]
    d = pd.Series(idx).diff().dt.total_seconds().div(60)
    # weekday gaps > 60 min that are not the daily 21-23 UTC rollover/ weekend
    big = [(str(idx[i - 1]), int(d.iloc[i])) for i in np.where(d > 180)[0]
           if idx[i - 1].dayofweek < 4 or (idx[i - 1].dayofweek == 4 and idx[i - 1].hour < 20)]
    per_month = df.groupby(df.index.to_period("M")).size()
    rows.append(dict(sym=s, group=GROUP[s], first=str(idx[0]), last=str(idx[-1]), m1_bars=len(df),
                     min_month_bars=int(per_month.min()), min_month=str(per_month.idxmin()),
                     weekday_gaps_gt3h=len(big), worst_gaps=sorted(big, key=lambda x: -x[1])[:3]))
inv = pd.DataFrame(rows)
print(inv.drop(columns="worst_gaps").to_string())

# timezone / source cross-check vs Dukascopy raw days (UTC)
chk = []
for s in ["XAGUSD", "NAS100", "WTI", "USDJPY"]:
    p = DUKA_RAW / s
    if not p.exists():
        continue
    for f in sorted(p.glob("*.bi5")):
        day = dt.datetime.strptime(f.stem, "%Y%m%d").date()
        d = decode(s, day, f.read_bytes())
        if d is None or d.empty:
            continue
        h = load_m1(s)
        h = h[(h.index >= d.index[0]) & (h.index <= d.index[-1])]
        best = None
        for lag in range(-120, 121, 30):
            x = d.close.copy(); x.index = x.index + pd.Timedelta(minutes=lag)
            j = pd.concat([x.rename("duka"), h.close.rename("hd")], axis=1, sort=True).dropna()
            if len(j) < 100:
                continue
            err = float((j.duka - j.hd).abs().median() / j.hd.median() * 1e4)  # bp
            if best is None or err < best[1]:
                best = (lag, err, len(j))
        if best is None:
            continue
        chk.append(dict(sym=s, day=str(day), best_lag_min=best[0], median_abs_diff_bp=round(best[1], 2), n=best[2]))
chk = pd.DataFrame(chk)
print(chk.to_string())
(OUT / "data_inventory.json").write_text(json.dumps({"inventory": rows, "duka_crosscheck": chk.to_dict("records")}, indent=1, default=str))
