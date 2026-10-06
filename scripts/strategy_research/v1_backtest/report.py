"""Aggregate run_v1.py checkpoints -> summary.json + tables (markdown) + trade lists."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "ob_final")); sys.path.insert(0, str(HERE.parent))
import core as C  # noqa
from run_v1 import TR_DIR, ASSETS, V1_MAP  # noqa

OUT = C.ROOT / "data/backtest/strategy_research/v1_backtest"; OUT.mkdir(parents=True, exist_ok=True)
SPLIT = C.SPLIT.value; END = C.END.value
TEST_WK = C.weeks(C.SPLIT, C.END)

tr = pd.concat([pd.read_parquet(TR_DIR / f"{s}.parquet") for s in ASSETS], ignore_index=True)
bl = pd.concat([pd.read_parquet(TR_DIR / f"baseline_{s}.parquet") for s in ASSETS], ignore_index=True)
zs = pd.concat([pd.read_parquet(TR_DIR / f"zones_{s}.parquet") for s in ASSETS], ignore_index=True)
tr["group"] = tr.sym.map(C.GROUP); bl["group"] = bl.sym.map(C.GROUP)
tr["period"] = np.where(tr.t_fill < SPLIT, "train", "test")
bl["period"] = np.where(bl.t_fill < SPLIT, "train", "test")
tr["year"] = pd.to_datetime(tr.t_fill, utc=True).dt.year
train_start = pd.to_datetime(zs.t_active.min(), utc=True)
TRAIN_WK = C.weeks(train_start, C.SPLIT)


def m(x: pd.DataFrame, wk: float, col="r_net") -> dict:
    x = x.sort_values("t_fill")
    d = C.metrics(x[col].to_numpy(float), wk)
    d["hold_h"] = float(x.hold_min.mean() / 60) if len(x) else np.nan
    d["time_exit_share"] = float((x.why >= 3).mean()) if len(x) else np.nan
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


S = {"meta": {"assets": V1_MAP, "excluded_v1_symbols": ["US30 (YM=F)", "RUSSELL (RTY=F)", "NZDUSD", "OIL (CL=F)"],
              "split": str(C.SPLIT), "end": str(C.END), "train_start_first_zone": str(train_start),
              "test_weeks": round(TEST_WK, 2), "alerts_5star": zs.groupby("tf").size().to_dict(),
              "alerts_5star_test": zs[zs.t_active >= SPLIT].groupby("tf").size().to_dict()},
     "configs": {}}
rows = []
for cfg in ("native", "mid_1h", "mid_3h"):
    a = tr[tr.cfg == cfg]
    net = a[a.cost == 1.0]; gro = a[a.cost == 0.0]; c15 = a[a.cost == 1.5]
    b1 = bl[(bl.cfg == cfg) & (bl.cost == 1.0)]; b0 = bl[(bl.cfg == cfg) & (bl.cost == 0.0)]
    d = {}
    for per, wk in (("test", TEST_WK), ("train", TRAIN_WK)):
        d[per] = {"net": m(net[net.period == per], wk), "gross": m(gro[gro.period == per], wk, "r_gross"),
                  "net_1.5x": m(c15[c15.period == per], wk),
                  "random_net": m(b1[b1.period == per].assign(hold_min=np.nan, why=0).rename(columns={"r": "r_net"}), wk),
                  "random_gross": m(b0[b0.period == per].assign(hold_min=np.nan, why=0).rename(columns={"r": "r_net"}), wk)}
        d[per]["random_net"]["n"] = int(d[per]["random_net"]["n"] / 3)  # 3 draws
    tn = net[net.period == "test"]
    d["test_by_group"] = {g: m(x, TEST_WK) for g, x in tn.groupby("group")}
    d["test_by_tf"] = {g: m(x, TEST_WK) for g, x in tn.groupby("tf")}
    d["test_by_group_tf"] = {f"{g}|{t}": m(x, TEST_WK) for (g, t), x in tn.groupby(["group", "tf"])}
    d["test_by_group_gross"] = {g: round(float(x.r_gross.mean()), 4) for g, x in gro[gro.period == "test"].groupby("group")}
    d["test_by_tf_gross"] = {g: round(float(x.r_gross.mean()), 4) for g, x in gro[gro.period == "test"].groupby("tf")}
    d["test_by_symbol"] = {g: m(x, TEST_WK) for g, x in tn.groupby("sym")}
    d["by_year_net"] = {int(y): round(float(x.r_net.mean()), 4) for y, x in net.groupby("year")}
    d["by_year_n"] = {int(y): int(len(x)) for y, x in net.groupby("year")}
    d["test_by_side"] = {("long" if s > 0 else "short"): m(x, TEST_WK) for s, x in tn.groupby("side")}
    d["test_exit_reasons"] = {C_: int(v) for C_, v in tn.why.map({1: "tp", 2: "sl", 3: "time", 4: "eod"}).value_counts().items()}
    d["test_median_risk_pct"] = round(float(tn.risk_pct.median() * 100), 4)
    d["test_cost_drag_R"] = round(float(d["test"]["gross"]["avg"] - d["test"]["net"]["avg"]), 4)
    S["configs"][cfg] = d
    t_ = d["test"]
    rows.append([cfg, t_["net"]["n"], round(t_["net"]["per_wk"], 2), f'{t_["net"]["wr"]*100:.1f}%', f'{t_["gross"]["avg"]:+.3f}',
                 f'{t_["net"]["avg"]:+.3f} [{t_["net"]["lo"]:+.3f}, {t_["net"]["hi"]:+.3f}]', f'{t_["net"]["pf"]:.2f}',
                 f'{t_["net"]["maxdd"]:.1f}', f'{t_["net"]["hold_h"]:.1f} h', f'{t_["net_1.5x"]["avg"]:+.3f}',
                 f'{d["train"]["net"]["avg"]:+.3f} [{d["train"]["net"]["lo"]:+.3f}, {d["train"]["net"]["hi"]:+.3f}] (n={d["train"]["net"]["n"]})',
                 f'{t_["random_net"]["avg"]:+.3f} / {t_["random_gross"]["avg"]:+.3f}'])

hdr = ["Config", "TEST trades", "Trades/wk", "WR (net)", "Avg R gross", "Avg R net [95% CI]", "PF net", "MaxDD R",
       "Avg hold", "Net @1.5x cost", "TRAIN avg R net [95% CI]", "Random TEST net / gross"]
md = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows]
nat = S["configs"]["native"]
def brk(dct, gross):
    out = ["| Bucket | n | Trades/wk | WR | Gross | Net [95% CI] | PF | MaxDD R |", "|---|---:|---:|---:|---:|---|---:|---:|"]
    for k, v in dct.items():
        out.append(f'| {k} | {v["n"]} | {v["per_wk"]:.2f} | {v["wr"]*100:.1f}% | {gross.get(k, float("nan")):+.3f} | '
                   f'{v["avg"]:+.3f} [{v["lo"]:+.3f}, {v["hi"]:+.3f}] | {v["pf"]:.2f} | {v["maxdd"]:.1f} |')
    return out
gtf = {}
md += ["", "Native, TEST, by group:"] + brk(nat["test_by_group"], nat["test_by_group_gross"])
md += ["", "Native, TEST, by timeframe:"] + brk(nat["test_by_tf"], nat["test_by_tf_gross"])
md += ["", "Native, TEST, group x TF (net avg R, n):", "| Group | M5 | M15 | H1 |", "|---|---|---|---|"]
for g in ("METALS", "FOREX", "INDICES", "CRYPTO"):
    cells = []
    for t in ("M5", "M15", "H1"):
        v = nat["test_by_group_tf"].get(f"{g}|{t}")
        cells.append(f'{v["avg"]:+.3f} (n={v["n"]})' if v else "-")
    md.append(f"| {g} | " + " | ".join(cells) + " |")
md += ["", "Native, net avg R by fill year: " + ", ".join(f"{y}: {v:+.3f} (n={nat['by_year_n'][y]})" for y, v in nat["by_year_net"].items())]
(OUT / "tables.md").write_text("\n".join(md) + "\n")
(OUT / "summary.json").write_text(json.dumps(S, indent=1, default=float))
keep = ["sym", "group", "tf", "side", "cfg", "period", "zhi", "zlo", "level", "sl", "tp_px", "t_active", "t_fill", "t_exit",
        "hold_min", "why", "r_gross", "r_net", "risk_pct", "lag_bars"]
x = tr[tr.cost == 1.0][keep].copy()
for c in ("t_active", "t_fill", "t_exit"): x[c] = pd.to_datetime(x[c], utc=True)
x["why"] = x.why.map({1: "tp", 2: "sl", 3: "time", 4: "eod"})
x.to_parquet(OUT / "trades_all_cost1.parquet")
x[(x.cfg == "native") & (x.period == "test")].to_csv(OUT / "trades_native_test.csv", index=False)
print("\n".join(md))
