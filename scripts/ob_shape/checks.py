"""Structural checks on prod + hist zones (detection oddities, alert duplicates, phantom reactions)."""
import json
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
RES = HERE / "results"
H = pd.read_parquet(RES / "hist_zones.parquet")
P = pd.read_csv(RES / "prod_zones.csv")
A = pd.read_csv(RES / "prod_alerts_sent.csv")
L = []
def pr(s=""):
    L.append(s); print(s)
for name, d in (("hist", H), ("prod", P), ("prod_alerted", P[P.alerted == 1])):
    n = len(d)
    pr(f"## {name} (n={n})")
    pr(f"- OB candle before the broken pivot (OB is not part of the leg that broke structure): {(d.ob_before_pivot==1).sum()} ({(d.ob_before_pivot==1).mean():.1%})")
    pr(f"- OB not at the leg extreme (leg_gap>0): {(d.leg_gap>0).sum()} ({(d.leg_gap>0).mean():.1%}); leg extreme > 0.1 ATR beyond the zone (SL above/below the real swing): {(d.leg_ext_beyond_atr>0.1).sum()} ({(d.leg_ext_beyond_atr>0.1).mean():.1%})")
    pr(f"- zone top above the broken level (bull) / bottom below (bear) (ob_to_bos_atr<0): {(d.ob_to_bos_atr<0).sum()}")
    pr(f"- BOS margin < 0.1 ATR (barely broke a pivot): {(d.bos_margin_atr<0.1).sum()} ({(d.bos_margin_atr<0.1).mean():.1%}); BOS bars from OB median {d.bos_bars.median():.0f}; broken pivot age median {d.piv_age.median():.0f} bars")
    pr(f"- born in chop (>5 of 10 prior bars overlap the zone): {(d.chop10>5).sum()} ({(d.chop10>5).mean():.1%})")
    pr(f"- wick-dominated OB candle (body < 25% of range): {(d.ob_body_ratio<0.25).sum()} ({(d.ob_body_ratio<0.25).mean():.1%})")
    pr(f"- weak displacement (max body OB+1..2 < 1 ATR): {(d.disp_maxbody_atr<1).sum()} ({(d.disp_maxbody_atr<1).mean():.1%}); tiny FVG < 0.25 ATR: {(d.fvg_atr<0.25).sum()} ({(d.fvg_atr<0.25).mean():.1%})")
    pr(f"- entry = OB open (zone <= 1 ATR) instead of the 50% mid: {(d.entry_mid==0).sum()} ({(d.entry_mid==0).mean():.1%})")
    pr(f"- touch bar opened at/through the entry (gap fill): {(d.gap_entry==1).sum()}; prev close already beyond the proximal edge (gap across): {(d.prev_close_dist_atr<0).sum()}")
    pr(f"- NOT textbook (>=2 of T1-T8 fail): {(d.tb_fails>=2).sum()} ({(d.tb_fails>=2).mean():.1%}); >=3 fails: {(d.tb_fails>=3).sum()} ({(d.tb_fails>=3).mean():.1%})")
    life = d["status"] if "status" in d else d["life"]
    r = d[life == "reaction"]
    pr(f"- 'Réaction +2R' status but a resting entry limit hit SL first: {(r.hold=='sl').sum()}/{len(r)} ({(r.hold=='sl').mean():.1%})")
    pr("")
# prod risk size in pips / % for FX
fx = P[P.group == "FOREX"].copy()
pip = np.where(fx.symbol.str.contains("JPY"), 0.01, 0.0001)
fx["risk_pips"] = (fx.entry - fx.sl).abs() / pip
pr("## Prod FOREX risk (entry→SL) in pips by TF (median / share < 3 pips)")
pr(fx.groupby("tf").risk_pips.agg(["count", "median", lambda s: (s < 3).mean()]).round(2).to_markdown())
pr("")
# alert duplicates
g = A.groupby(["symbol", "tf", "direction", "lo_s", "hi_s", "event"]).size()
dup = g[g > 1]
pr(f"## Telegram: same zone+event sent more than once: {len(dup)} cases")
pr(dup.to_markdown() if len(dup) else "none")
pr("")
# SL message while trade_sim says the mid entry was not reached
lines = [json.loads(x) for x in open("/workspace/ob_shape/prod/results/telegram_dryrun.log")]
c = [l for l in lines if not l.get("dry_run") and "Invalidation" in l["text"] and "pas encore atteinte" in l["text"]]
pr(f"## 'Invalidation / SL' messages that also say 'entrée mid pas encore atteinte': {len(c)} of "
   f"{sum(1 for l in lines if not l.get('dry_run') and 'Invalidation' in l['text'])} SL messages")
lab = [l for l in lines if not l.get("dry_run") and "(milieu OB)" in l["text"]]
pr(f"## Messages labelled '(milieu OB)': {len(lab)} — but for zones <= 1 ATR the engine uses the OB OPEN, not the mid "
   f"(prod alerted zones with entry = open: {(P[P.alerted==1].entry_mid==0).sum()}/{(P.alerted==1).sum()})")
(RES / "checks.md").write_text("\n".join(L))
