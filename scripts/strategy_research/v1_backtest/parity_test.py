"""Parity: Python port (v1_core.detect_full + sltp_v1) vs the original v1 JS detectOrderBlocks on v1's own cached
candles (3 files, 3 TFs). Prints mismatches; exit 1 if any."""
import json, subprocess, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v1_core as V
bad = 0; tot = 0
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "v1_snapshot"
for f in sorted(SRC.glob("*_*.json")):
    if len(json.loads(f.read_text()).get("candles", [])) < 40: continue
    d = json.loads(f.read_text()); cs = d["candles"]
    o, h, l, c = (np.array([x[k] for x in cs], float) for k in ("open", "high", "low", "close"))
    js = json.loads(subprocess.check_output(["node", str(HERE / "parity_harness.mjs"), str(f)]))
    di, oi, sd, F = V.detect_full(o, h, l, c)
    en, sl, tp = V.sltp_v1(h[oi], l[oi], sd)
    py = {(int(a), int(b_), int(s_)): (list(map(bool, ff)), e_, s2, t2) for a, b_, s_, ff, e_, s2, t2 in zip(di, oi, sd, F, en, sl, tp)}
    jsd = {(r[0], r[1], r[2]): (r[3:8], r[8], r[9], r[10]) for r in js}
    keys = set(py) | set(jsd)
    mism = [k for k in keys if k not in py or k not in jsd or py[k][0] != jsd[k][0]
            or max(abs(py[k][1] - jsd[k][1]), abs(py[k][2] - jsd[k][2]), abs(py[k][3] - jsd[k][3])) > 1e-9 * max(1, abs(jsd[k][1]))]
    n5 = sum(1 for k in jsd if sum(jsd[k][0]) == 5)
    print(f"{f.name}: candles={len(cs)} obs JS={len(jsd)} PY={len(py)} 5star(JS)={n5} mismatches={len(mism)}")
    bad += len(mism); tot += len(keys)
print("PARITY", "OK" if bad == 0 else f"FAIL ({bad}/{tot})")
sys.exit(1 if bad else 0)
