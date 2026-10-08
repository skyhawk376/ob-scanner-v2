"""TRAIN-only univariate exploration (hist zones, touch < 2025-07-01). Prints AUC per feature."""
import sys
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu
pd.set_option("display.width", 250)
d = pd.read_parquet("results/hist_zones.parquet")
d = d[d.ts_touch < pd.Timestamp("2025-07-01", tz="UTC")]
d = d[d.hold.isin(["tp", "sl"])].copy()
d["y"] = (d.hold == "tp").astype(int)
FEATS = ["ob_range_atr", "ob_body_ratio", "ob_prox_wick", "ob_dist_wick", "zone_h_atr", "entry_mid", "risk_atr",
         "disp1_body_atr", "disp1_range_atr", "disp1_body_pct", "disp_maxbody_atr", "disp_n", "impulse3_atr", "fvg_atr",
         "bos_bars", "bos_margin_atr", "ob_to_bos_atr", "piv_age", "leg_gap", "leg_ext_beyond_atr", "opp_between",
         "leg_len_atr", "ob_before_pivot", "chop10", "chop20", "range20_atr", "sweep_leg", "touch_bars", "touch_after_bos",
         "run_after_bos_atr", "approach_bars", "approach_speed", "touch_range_atr", "touch_body_atr", "touch_toward",
         "touch_big", "mom3_atr", "consec_toward", "prev_close_dist_atr", "gap_entry", "touch_open_inside",
         "touch_close_through", "s2", "s3", "s4", "s5", "score", "aligned_h4d1", "bias_h4_ok", "bias_d1_ok", "tb_fails",
         "T1_displacement", "T2_fvg", "T3_bos_fast", "T4_bos_margin", "T5_origin", "T6_not_chop", "T7_body", "T8_size", "cost_r"]
tfs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["H1", "M15", "M30", "M5", "H4"]
d = d[d.tf.isin(tfs)]
print("n", len(d), "tp rate", d.y.mean().round(3), "r_gross", d.r_gross.mean().round(3))
rows = []
for f in FEATS:
    x = d[f].astype(float)
    ok = x.notna()
    a, b = x[ok & (d.y == 1)], x[ok & (d.y == 0)]
    u, p = mannwhitneyu(a, b)
    auc = u / (len(a) * len(b))
    # realistic R correlation (spearman)
    rg = d.loc[ok, "r_gross"]
    rho = x[ok & rg.notna()].rank().corr(rg[rg.notna()].rank())
    rows.append(dict(f=f, med_tp=a.median(), med_sl=b.median(), auc=auc, p=p, rho_rgross=rho))
r = pd.DataFrame(rows)
r["sep"] = (r.auc - 0.5).abs()
print(r.sort_values("sep", ascending=False).round(4).to_string(index=False))
