"""Signal generators for the 5 pre-registered families. Each returns order requests for common.simulate().
Every signal uses closed bars only; orders become live DELAY minutes after the signal (manual execution)."""
from __future__ import annotations
import itertools, pickle
import numpy as np, pandas as pd
from common import ROOT, GROUP, asof, bars, local, trend

DELAY = 3  # minutes between alert (signal bar close) and order live
EU = ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "GBPJPY", "DAX", "XAUUSD"]
US = ["XAUUSD", "XAGUSD", "EURUSD", "USDCAD", "NAS100", "US500", "BTC", "ETH"]
ALLB = sorted(set(EU) | set(US) | {"USDJPY", "AUDUSD", "USDCHF", "SOL"})
MFC = [s for s in ALLB if GROUP[s] in ("METALS", "FOREX", "CRYPTO")]
BASKETS = {"EU": EU, "US": US, "ALL": ALLB, "MFC": MFC}

def _req(**kw) -> dict:
    d = dict(tp_r=0.0, tp_abs=np.nan, expiry_min=0.0, hold_min=60.0)
    d.update(kw); return d

def _to_utc(dates: pd.Series, minutes: int, tz: str) -> pd.DatetimeIndex:
    t = pd.DatetimeIndex(dates) + pd.Timedelta(minutes=minutes)
    return t.tz_localize(tz, nonexistent="shift_forward", ambiguous=False).tz_convert("UTC")

def window_bars(sym: str, tz: str, a: int, b: int) -> pd.DataFrame:
    df = local(sym, tz)
    return df[(df["mod"] >= a) & (df["mod"] < b) & (df["dow"] < 5)]

# ------------------------------------------------------------------------------------------- C. ORB
ORB_OPENS = {"EU08": ("Europe/Paris", 8 * 60, EU), "EU09": ("Europe/Paris", 9 * 60, EU),
             "NY0930": ("America/New_York", 9 * 60 + 30, US)}

def orb_configs():
    for op, rng, slm, tp, flt in itertools.product(ORB_OPENS, (15, 30), ("opp", "mid"), (1, 2), ("none", "d1")):
        yield dict(family="C_ORB", open=op, range=rng, sl=slm, tp=tp, filter=flt)

_orb_cache: dict = {}
def _orb_ranges(sym, op, rng):
    k = (sym, op, rng)
    if k not in _orb_cache:
        tz, o, _ = ORB_OPENS[op]
        w = window_bars(sym, tz, o, o + rng)
        g = w.groupby("date").agg(hi=("high", "max"), lo=("low", "min"), n=("close", "size"))
        g = g[g.n >= 0.6 * rng].reset_index()
        g["t_end"] = _to_utc(g["date"], o + rng, tz)
        g["d1"] = trend(sym, "D1", g["t_end"], "ema20")
        _orb_cache[k] = g
    return _orb_cache[k]

def orb_requests(cfg) -> pd.DataFrame:
    rows = []
    for sym in ORB_OPENS[cfg["open"]][2]:
        g = _orb_ranges(sym, cfg["open"], cfg["range"])
        for r in g.itertuples():
            if r.hi <= r.lo:
                continue
            mid = (r.hi + r.lo) / 2
            ta = r.t_end + pd.Timedelta(minutes=DELAY)
            oco = f"{sym}|{r.date.date()}|{cfg['open']}"
            base = dict(sym=sym, t_active=ta, etype="stop", tp_r=float(cfg["tp"]), expiry_min=120 - DELAY, oco=oco, sig_time=r.t_end)
            if cfg["filter"] != "d1" or r.d1 > 0:
                rows.append(_req(**base, side=1, level=r.hi, sl=(r.lo if cfg["sl"] == "opp" else mid)))
            if cfg["filter"] != "d1" or r.d1 < 0:
                rows.append(_req(**base, side=-1, level=r.lo, sl=(r.hi if cfg["sl"] == "opp" else mid)))
    return pd.DataFrame(rows)

# -------------------------------------------------------------------------------- B. liquidity sweep
SWEEP_WIN = {"LON": (0, 8 * 60, 11 * 60, EU), "NY": (0, 14 * 60 + 30, 17 * 60, US)}

def sweep_configs():
    for win, ent, tp in itertools.product(SWEEP_WIN, ("market", "limit"), ("1R", "2R", "mid")):
        yield dict(family="B_SWEEP", window=win, entry=ent, tp=tp)

_sweep_cache: dict = {}
def _sweep_signals(sym, win):
    if (sym, win) in _sweep_cache:
        return _sweep_cache[(sym, win)]
    r0, a, b, _ = SWEEP_WIN[win]
    tz = "Europe/Paris"
    rng = window_bars(sym, tz, r0, a).groupby("date").agg(hi=("high", "max"), lo=("low", "min"), n=("close", "size"))
    rng = rng[rng.n >= 0.5 * (a - r0) * (0.7 if GROUP[sym] != "CRYPTO" else 1.0)]
    w = window_bars(sym, tz, a, b).copy()
    w["m5"] = w["mod"] // 5
    m5 = w.groupby(["date", "m5"]).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    sigs = []
    for date, day in m5.groupby(level=0):
        if date not in rng.index:
            continue
        hi, lo = rng.at[date, "hi"], rng.at[date, "lo"]
        H = day["high"].to_numpy(); L = day["low"].to_numpy(); C = day["close"].to_numpy()
        slots = day.index.get_level_values(1).to_numpy()
        up_ext = dn_ext = None
        for k in range(len(C)):
            if H[k] > hi:
                up_ext = H[k] if up_ext is None else max(up_ext, H[k])
            if L[k] < lo:
                dn_ext = L[k] if dn_ext is None else min(dn_ext, L[k])
            side = 0
            if up_ext is not None and C[k] < hi:
                side, ext, lvl = -1, up_ext, hi
            elif dn_ext is not None and C[k] > lo:
                side, ext, lvl = 1, dn_ext, lo
            if side:
                t_close = _to_utc(pd.Series([date]), int(slots[k]) * 5 + 5, tz)[0]
                sigs.append(dict(date=date, side=side, ext=ext, lvl=lvl, close=C[k], hi=hi, lo=lo, t_sig=t_close))
                break
    s = pd.DataFrame(sigs)
    if len(s):
        s["atr"] = asof(sym, "H1", s["t_sig"], "atr")
    _sweep_cache[(sym, win)] = s
    return s

def sweep_requests(cfg) -> pd.DataFrame:
    rows = []
    for sym in SWEEP_WIN[cfg["window"]][3]:
        s = _sweep_signals(sym, cfg["window"])
        for r in s.itertuples():
            sl = r.ext + 0.1 * r.atr if r.side < 0 else r.ext - 0.1 * r.atr
            mid = (r.hi + r.lo) / 2
            ref = r.close if cfg["entry"] == "market" else r.lvl
            if cfg["tp"] == "mid" and ((r.side > 0 and mid <= ref) or (r.side < 0 and mid >= ref)):
                continue
            tp_r = {"1R": 1.0, "2R": 2.0, "mid": 0.0}[cfg["tp"]]
            rows.append(_req(sym=sym, t_active=r.t_sig + pd.Timedelta(minutes=DELAY), side=int(r.side),
                             etype=cfg["entry"], level=float(ref), sl=float(sl), tp_r=tp_r,
                             tp_abs=float(mid) if cfg["tp"] == "mid" else np.nan,
                             expiry_min=60.0, sig_time=r.t_sig))
    return pd.DataFrame(rows)

# --------------------------------------------------------------------------------- D. FVG retest M15
FVG_WIN = {"EU": (8 * 60, 12 * 60, EU), "US": (14 * 60 + 30, 18 * 60, US)}

def fvg_configs():
    for win, tr, ent, slm, tp in itertools.product(FVG_WIN, ("H1", "H4"), ("prox", "mid"), ("gap", "c1"), (1, 2)):
        yield dict(family="D_FVG", window=win, trend=tr, entry=ent, sl=slm, tp=tp)

_fvg_cache: dict = {}
def _fvg_all(sym):
    if sym in _fvg_cache:
        return _fvg_cache[sym]
    b = bars(sym, "M15")
    h, l, atr = b.high.to_numpy(), b.low.to_numpy(), b.atr.to_numpy()
    h2, l2 = np.roll(h, 2), np.roll(l, 2)
    contiguous = (b.index.to_series().diff(2).dt.total_seconds().to_numpy() == 1800)
    bull = (l > h2) & ((l - h2) >= 0.3 * atr) & contiguous
    bear = (h < l2) & ((l2 - h) >= 0.3 * atr) & contiguous
    rows = []
    for i in np.where(bull | bear)[0]:
        if i < 2:
            continue
        side = 1 if bull[i] else -1
        rows.append(dict(t_sig=b["tclose"].iloc[i], side=side,
                         prox=l[i] if side > 0 else h[i], far=h2[i] if side > 0 else l2[i],
                         c1=l2[i] if side > 0 else h2[i], atr=atr[i]))
    f = pd.DataFrame(rows)
    loc = pd.DatetimeIndex(f["t_sig"]).tz_convert("Europe/Paris")
    f["mod"] = loc.hour * 60 + loc.minute; f["date"] = loc.tz_localize(None).normalize(); f["dow"] = loc.dayofweek
    f["H1"] = trend(sym, "H1", f["t_sig"], "ema50"); f["H4"] = trend(sym, "H4", f["t_sig"], "ema50")
    _fvg_cache[sym] = f
    return f

def fvg_requests(cfg) -> pd.DataFrame:
    a, b, basket = FVG_WIN[cfg["window"]]
    rows = []
    for sym in basket:
        f = _fvg_all(sym)
        f = f[(f["mod"] > a) & (f["mod"] <= b) & (f["dow"] < 5) & (f["side"] == f[cfg["trend"]])]
        f = f.groupby("date").head(1)
        for r in f.itertuples():
            lvl = r.prox if cfg["entry"] == "prox" else (r.prox + r.far) / 2
            ext = r.far if cfg["sl"] == "gap" else r.c1
            sl = ext - 0.1 * r.atr if r.side > 0 else ext + 0.1 * r.atr
            rows.append(_req(sym=sym, t_active=r.t_sig + pd.Timedelta(minutes=DELAY), side=int(r.side), etype="limit",
                             level=float(lvl), sl=float(sl), tp_r=float(cfg["tp"]), expiry_min=120.0, sig_time=r.t_sig))
    return pd.DataFrame(rows)

# ------------------------------------------------------------------------------ E. prev-day H/L baseline
PD_WIN = {"EU": (8 * 60, 12 * 60, EU), "US": (14 * 60 + 30, 18 * 60, US)}

def pdhl_configs():
    for mode, win, tp in itertools.product(("fade", "break"), PD_WIN, (1, 2)):
        yield dict(family="E_PDHL", mode=mode, window=win, tp=tp)

_pd_cache: dict = {}
def _pd_days(sym, win):
    if (sym, win) in _pd_cache:
        return _pd_cache[(sym, win)]
    a, b, _ = PD_WIN[win]
    w = window_bars(sym, "Europe/Paris", a, b)
    first = w.groupby("date").agg(o=("open", "first"))
    first["t0"] = _to_utc(first.index.to_series(), a, "Europe/Paris")
    first["pdh"] = asof(sym, "D1", first["t0"], "high"); first["pdl"] = asof(sym, "D1", first["t0"], "low")
    first["atr"] = asof(sym, "H1", first["t0"], "atr")
    first = first.dropna()
    _pd_cache[(sym, win)] = first.reset_index()
    return _pd_cache[(sym, win)]

def pdhl_requests(cfg) -> pd.DataFrame:
    a, b, basket = PD_WIN[cfg["window"]]
    rows = []
    for sym in basket:
        for r in _pd_days(sym, cfg["window"]).itertuples():
            if not (r.pdl < r.o < r.pdh):
                continue
            oco = f"{sym}|{r.date.date()}|{cfg['window']}"
            base = dict(sym=sym, t_active=r.t0, tp_r=float(cfg["tp"]), expiry_min=float(b - a), oco=oco, sig_time=r.t0)
            if cfg["mode"] == "fade":
                rows.append(_req(**base, side=-1, etype="limit", level=r.pdh, sl=r.pdh + r.atr))
                rows.append(_req(**base, side=1, etype="limit", level=r.pdl, sl=r.pdl - r.atr))
            else:
                rows.append(_req(**base, side=1, etype="stop", level=r.pdh, sl=r.pdh - r.atr))
                rows.append(_req(**base, side=-1, etype="stop", level=r.pdl, sl=r.pdl + r.atr))
    return pd.DataFrame(rows)

# ------------------------------------------------------------------------------------------ A. OB 5★
SESS = (8 * 60, 18 * 60)

def ob_configs():
    for ms, tf, tp, ses, bk in itertools.product((4, 5), ("none", "D1", "H4"), (1, 2), ("any", "0818"), ("MFC", "ALL")):
        yield dict(family="A_OB", min_score=ms, trend=tf, tp=tp, session=ses, basket=bk)

_ob_cache: dict = {}
def _ob_zones():
    if "z" not in _ob_cache:
        raw = pickle.loads((ROOT / "data/cache/strategy_research/ob_zones.pkl").read_bytes())
        rows = []
        for sym, zs in raw.items():
            for z in zs:
                rows.append(dict(sym=sym, level_ge=z["level"], side=1 if z["direction"] == "bull" else -1,
                                 entry=z["entry"], sl=z["sl"], det_time=pd.Timestamp(z["det_time"]), score=z["score"]))
        df = pd.DataFrame(rows)
        parts = []
        for sym, g in df.groupby("sym"):
            g = g.copy()
            g["D1"] = trend(sym, "D1", g["det_time"], "ema20"); g["H4"] = trend(sym, "H4", g["det_time"], "ema50")
            parts.append(g)
        _ob_cache["z"] = pd.concat(parts)
    return _ob_cache["z"]

def ob_requests(cfg) -> pd.DataFrame:
    z = _ob_zones()
    z = z[(z.level_ge == cfg["min_score"]) & z.sym.isin(BASKETS[cfg["basket"]])]
    if cfg["trend"] != "none":
        z = z[z["side"] == z[cfg["trend"]]]
    return pd.DataFrame(dict(sym=z.sym, t_active=z.det_time + pd.Timedelta(minutes=DELAY), side=z.side, etype="limit",
                             level=z.entry, sl=z.sl, tp_r=float(cfg["tp"]), tp_abs=np.nan, expiry_min=24 * 60.0,
                             hold_min=60.0, sig_time=z.det_time, sess_filter=cfg["session"]))

FAMILIES = {
    "A_OB": (ob_configs, ob_requests),
    "B_SWEEP": (sweep_configs, sweep_requests),
    "C_ORB": (orb_configs, orb_requests),
    "D_FVG": (fvg_configs, fvg_requests),
    "E_PDHL": (pdhl_configs, pdhl_requests),
}
