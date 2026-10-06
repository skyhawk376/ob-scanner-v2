"""Apply the pre-registered selection on TRAIN, then evaluate the frozen picks on TEST.
Outputs (data/backtest/strategy_research/): selection.json, winners_test.csv, winners_detail.json, top_train_overall.csv
"""
from __future__ import annotations
import ast, glob, json, math, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
import families as F
from common import OUT, ROOT, TEST, TRAIN, metrics, split
from run_grid import TR_DIR, cfg_name, post, run_cfg

FAMS = ["A_OB", "B_SWEEP", "C_ORB", "D_FVG", "E_PDHL"]

def load_trades(name: str) -> pd.DataFrame:
    return pd.read_parquet(TR_DIR / (name.replace("|", "__").replace("=", "-") + ".parquet"))

def fod(tr: pd.DataFrame) -> pd.DataFrame:
    """First FILLED trade per Paris calendar day, portfolio-wide (trader takes the first fill, cancels the rest)."""
    if tr.empty:
        return tr
    d = pd.DatetimeIndex(tr["t_fill"]).tz_convert("Europe/Paris").normalize()
    return tr.assign(_d=d).sort_values("t_fill").groupby("_d").head(1).drop(columns="_d").reset_index(drop=True)

def row_from(name, fam, tr):
    a, b = split(tr)
    r = dict(name=name, family=fam)
    r.update({f"tr_{k}": v for k, v in metrics(a, TRAIN).items()})
    r["_test"] = metrics(b, TEST)
    return r

def cfg_from_name(name: str) -> dict:
    d = {}
    for kv in name.replace("|fod", "").split("|"):
        k, v = kv.split("=", 1)
        try:
            v = ast.literal_eval(v)
        except Exception:
            pass
        d[k] = v
    return d

def breakdown(tr: pd.DataFrame, by: str) -> dict:
    out = {}
    for k, g in tr.groupby(by):
        m = metrics(g, (g.t_fill.min(), g.t_fill.max() + pd.Timedelta(days=1)))
        out[str(k)] = dict(n=m["n"], wr=round(m["wr"], 3), avg=round(m["avg"], 3), sum=round(m["sum"], 1))
    return out

def variant(name: str, fam: str, hold=60, cost=1.0, delay=3) -> pd.DataFrame:
    cfg = cfg_from_name(name)
    _, tr = run_cfg((fam, cfg, hold, cost, delay))
    return fod(tr) if name.endswith("|fod") else tr

def main():
    rows = []
    for fam in FAMS:
        p = OUT / f"grid_train_{fam}.csv"
        if not p.exists():
            print("missing", fam); continue
        for name in pd.read_csv(p)["name"]:
            tr = load_trades(name)
            rows.append(row_from(name, fam, tr))
            n_wd = rows[-1]["tr_per_wd"]
            if n_wd > 2.0:
                rows.append(row_from(name + "|fod", fam, fod(tr)))
    allr = pd.DataFrame(rows)
    K = len(allr)
    elig = allr[(allr.tr_n >= 150) & (allr.tr_per_wd >= 0.5) & (allr.tr_per_wd <= 3.0)].copy()
    winners = elig.sort_values("tr_t", ascending=False).groupby("family").head(1)
    winners = winners.sort_values("tr_t", ascending=False)
    top = elig.sort_values("tr_t", ascending=False).head(10)
    sel = dict(K_configs=int(K), eligible=int(len(elig)), bonferroni_t=round(float(abs(__import__("scipy.stats", fromlist=["norm"]).norm.ppf(0.025 / K))), 2),
               winners=winners["name"].tolist(), top10_train=top["name"].tolist())
    (OUT / "selection.json").write_text(json.dumps(sel, indent=1))
    print(json.dumps(sel, indent=1))
    allr.drop(columns="_test").to_csv(OUT / "all_configs_train.csv", index=False)

    # ---------------- TEST of frozen picks
    out_rows, detail = [], {}
    picks = list(dict.fromkeys(winners["name"].tolist() + top["name"].tolist()))
    for name in picks:
        fam = allr.loc[allr.name == name, "family"].iloc[0]
        r = allr.loc[allr.name == name].iloc[0]
        base = load_trades(name.replace("|fod", "")); base = fod(base) if name.endswith("|fod") else base
        a, b = split(base)
        mt = metrics(b, TEST)
        row = dict(name=name, family=fam, winner=name in winners["name"].tolist(),
                   tr_n=r.tr_n, tr_per_wd=r.tr_per_wd, tr_avg=r.tr_avg, tr_t=r.tr_t,
                   **{f"te_{k}": v for k, v in mt.items()})
        d = {"train": metrics(a, TRAIN), "test": mt}
        if row["winner"]:
            for cm in (1.5, 2.0):
                _, bb = split(variant(name, fam, cost=cm)); row[f"te_avg_cost{cm:g}"] = metrics(bb, TEST)["avg"]
            for dl in (1, 5):
                _, bb = split(variant(name, fam, delay=dl)); row[f"te_avg_delay{dl}"] = metrics(bb, TEST)["avg"]
            for hd in (120, 240):
                aa, bb = split(variant(name, fam, hold=hd)); row[f"tr_avg_hold{hd}"] = metrics(aa, TRAIN)["avg"]; row[f"te_avg_hold{hd}"] = metrics(bb, TEST)["avg"]
            b = b.assign(q=pd.DatetimeIndex(b.t_fill).tz_convert("UTC").to_period("Q").astype(str))
            a = a.assign(y=pd.DatetimeIndex(a.t_fill).tz_convert("UTC").year)
            d["test_by_quarter"] = breakdown(b, "q"); d["train_by_year"] = breakdown(a, "y")
            d["test_by_group"] = breakdown(b, "group"); d["test_by_sym"] = breakdown(b, "sym")
            d["train_by_group"] = breakdown(a, "group"); d["train_by_sym"] = breakdown(a, "sym")
            d["test_exit_reasons"] = b["why"].value_counts().to_dict()
            row["te_quarters_pos"] = sum(1 for v in d["test_by_quarter"].values() if v["avg"] > 0)
            row["te_quarters"] = len(d["test_by_quarter"])
            base.to_csv(OUT / f"trades_winner_{fam}.csv", index=False)
        detail[name] = d
        out_rows.append(row)
    res = pd.DataFrame(out_rows)
    res.to_csv(OUT / "winners_test.csv", index=False)
    (OUT / "winners_detail.json").write_text(json.dumps(detail, indent=1, default=float))
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))

if __name__ == "__main__":
    main()
