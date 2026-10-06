"""Check: find_fill + run_exit (mgmt 0) == common._sim on random requests (EURUSD + XAUUSD, framework arrays)."""
import numpy as np, sys
import core as C
import common
rng = np.random.default_rng(0)
for sym in ("EURUSD", "XAUUSD", "BTC"):
    A = common.arrays(sym); N = len(A["t"]); n = 3000
    s = rng.integers(1000, N - 30000, n); side = rng.choice([-1, 1], n); et = rng.choice([0, 1], n)
    px = A["c"][s - 1]; atr = np.abs(A["h"][s-60:s].max() - A["l"][s-60:s].min()) if False else px * 0.002
    lvl = np.where(et == 1, px - side * atr * rng.uniform(0, 1, n), px)
    sl = lvl - side * atr * rng.uniform(0.3, 1.5, n)
    tpr = rng.choice([1.0, 2.0, 3.0], n); exp = (rng.integers(60, 1440, n) * 6e10).astype(np.int64)
    hold = (rng.integers(30, 3000, n) * 6e10).astype(np.int64)
    sp, cm, sli = zip(*[C.costs(sym, p) for p in lvl]); hs = np.array(sp) / 2; sli = np.array(sli)
    ref = common._sim(A["t"], A["o"], A["h"], A["l"], A["c"], s.astype(np.int64), side.astype(np.int64), et.astype(np.int64),
                      lvl, sl, tpr, np.full(n, np.nan), exp, hold, hs, sli)
    f, e, _ = C.find_fill(A["t"], A["o"], A["h"], A["l"], A["c"], s.astype(np.int64), side.astype(np.int64), et.astype(np.int64), lvl, exp, hs)
    epx_s = e + side * sli * (et == 0)
    risk = np.where(et == 0, side * (epx_s - sl), side * (lvl - sl))
    refp = np.where(et == 0, epx_s, lvl)
    T = refp + side * tpr * risk
    tl = np.full(N, -np.inf); th = np.full(N, np.inf)
    x, r, w, rk, ep = C.run_exit(A["t"], A["o"], A["h"], A["l"], A["c"], f, side.astype(np.int64), et.astype(np.int64), e, lvl, sl, T, hold, hs, sli, 0, tl, th)
    rf, rx, repx, rxpx, rrisk, rwhy = ref
    ok = rf >= 0
    rg_ref = side * (rxpx - repx) / rrisk
    same_fill = np.array_equal(rf, f); same_exit = np.array_equal(rx[ok], x[ok])
    same_why = np.array_equal(rwhy[ok], w[ok]); dr = np.nanmax(np.abs(rg_ref[ok & (rwhy < 5)] - r[ok & (rwhy < 5)]))
    print(sym, "fills", ok.sum(), "same_fill", same_fill, "same_exit", same_exit, "same_why", same_why, "max|dR|", dr)
