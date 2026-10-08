"""Regression: an active zone touched inside the last bar disappears from the next scan
(no longer virgin). It must NOT be deleted before the lifecycle refresh has checked the
candles since its last check: it ends ``touchee`` with exactly one first-touch alert
(all TFs), guarded by anti-doublon, go-live (armed_at) and a staleness limit."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from app.core.timeframes import ALL_TFS, TF_MINUTES

NOW0 = pd.Timestamp("2026-10-07T12:00:00Z")  # open of the bar that will be touched
LO, HI, ENTRY, SL, ATR = 1.100, 1.110, 1.105, 1.095, 0.01


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_DRY_RUN", "true")
    monkeypatch.setenv("FETCH_TFS", "M5,M15,M30,H1,H4,D,W")
    monkeypatch.setenv("STRATEGY_LOCK", "true")
    monkeypatch.delenv("ALERT_TFS", raising=False)
    from app.core import telegram as tg
    from app.core.config import get_settings

    get_settings.cache_clear()
    sends: list[str] = []
    monkeypatch.setattr(tg, "send_telegram", lambda text, **kw: sends.append(text) or {"ok": True})
    monkeypatch.sends = sends
    yield monkeypatch
    get_settings.cache_clear()


def _bars(tf: str, n_before: int = 30) -> pd.DataFrame:
    """OB bar (zone 1.100–1.110) then untouched bars above it, ending with the bar that
    opens at NOW0 (forming at the first scan)."""
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    idx = pd.date_range(end=NOW0, periods=n_before, freq=step)
    rows = []
    for i in range(n_before):
        if i == 5:  # OB candle (bearish) = the zone
            rows.append((1.108, HI, LO, 1.102))
        else:
            rows.append((1.120, 1.125, 1.115, 1.120))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def _append(df: pd.DataFrame, tf: str, rows) -> pd.DataFrame:
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    idx = [df.index[-1] + step * (k + 1) for k in range(len(rows))]
    add = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(idx))
    return pd.concat([df, add])


def _write(settings, symbol, tf, df):
    from app.core.cache import write_cache

    df = df.copy()
    df["volume"] = 0.0
    write_cache(settings.cache_dir, symbol, tf, df)


def _fake_detect(*, drop: bool = False):
    """Stand-in for detect_zones (detection rules untouched): reports the OB while it is
    still virgin on CLOSED bars (last bar = forming, excluded like the real engine)."""
    from app.engine.detect import is_fresh
    from app.engine.types import Zone

    def detect(df, *, symbol="SYM", tf="H1", params=None, min_score=None, require_fresh=None, **kw):
        work = df.iloc[:-1]
        ob_i = 5
        fresh = is_fresh(work["low"].to_numpy(), work["high"].to_numpy(), ob_i, LO, HI)
        if drop or (require_fresh and not fresh):
            return []
        ts_ob = work.index[ob_i].isoformat()
        return [Zone(
            id=f"{symbol}|{tf}|bull|{ts_ob}", symbol=symbol, tf=tf, direction="bull",
            ob_index=ob_i, bos_index=ob_i + 3, leg_index=ob_i, ts_ob=ts_ob,
            ts_bos=work.index[ob_i + 3].isoformat(), low=LO, high=HI, open=1.108, close=1.102,
            star1_fvg=True, star2_trend=True, star3_fib=True, star4_liquidity=True,
            star5_session=False, star5_pending=False, score=4, fresh=fresh, trend="bull",
            entry=ENTRY, sl=SL, tp1=None, tp2=ENTRY + 2 * (ENTRY - SL), rr_tp1=None, rr_tp2=2.0,
            atr=ATR, fib_eq=1.12, swing_low=LO, swing_high=1.125, distance_atr=1.5,
            last_close=float(work["close"].iloc[-1]),
        )]

    return detect


def _cycle(env, tf, *, now, notify_since, drop=False, symbols=("EURUSD",)):
    """One pipeline step for a TF: scan (persist) → lifecycle refresh, like jobs.run_pipeline."""
    import app.core.scanner as scanner
    from app.core.config import get_settings
    from app.core.monitor import refresh_statuses

    env.setattr(scanner, "detect_zones", _fake_detect(drop=drop))
    s = get_settings()
    ss = scanner.run_scan(tfs=[tf], groups=["FOREX"], symbols=list(symbols), min_score=4, settings=s)
    rs = refresh_statuses(tf=tf, groups=["FOREX"], min_score=4, notify=True,
                          force_dry_telegram=None, settings=s, notify_since=notify_since, now=now)
    return ss, rs


def _rows(settings, tf):
    from app.core.store import connect

    conn = connect(settings.db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT id, status, touched_at, vanished_at FROM zones WHERE tf=?", (tf,))]
    finally:
        conn.close()


@pytest.mark.parametrize("tf", ALL_TFS)
def test_touch_between_scans_alerts_once_all_tfs(env, tf):
    from app.core.config import get_settings
    from app.core.store import connect, list_zones

    s = get_settings()
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    armed = (NOW0 - 50 * step).timestamp()  # TF armed long before the touch
    df = _bars(tf)
    _write(s, "EURUSD", tf, df)
    ss, rs = _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=armed)
    assert len(ss.zones) == 1
    assert [r["status"] for r in _rows(s, tf)] == ["active"] and not env.sends

    # Price dips into the zone inside the bar that was forming at the last refresh;
    # that bar closes, a new one opens → the next scan no longer sees a virgin OB.
    df2 = _append(df.iloc[:-1], tf, [(1.120, 1.122, 1.108, 1.115), (1.115, 1.118, 1.113, 1.116)])
    _write(s, "EURUSD", tf, df2)
    now2 = (NOW0 + step + timedelta(minutes=1)).to_pydatetime()
    ss, rs = _cycle(env, tf, now=now2, notify_since=armed)
    assert ss.zones == []  # scan omits the touched zone
    rows = _rows(s, tf)
    assert len(rows) == 1 and rows[0]["status"] == "touchee"
    assert pd.Timestamp(rows[0]["touched_at"]) == NOW0  # bar of the touch
    assert rows[0]["vanished_at"]  # it left the scan, kept for lifecycle
    assert rs.vanished_touched == 1 and rs.vanished_pruned == 0 and rs.notifications == 1
    assert len(env.sends) == 1 and "EURUSD" in env.sends[0]

    # Following cycles: no duplicate alert, zone kept (touched zones are never pruned)
    for k in (2, 3):
        _cycle(env, tf, now=(NOW0 + k * step).to_pydatetime(), notify_since=armed)
    assert len(env.sends) == 1
    assert [r["status"] for r in _rows(s, tf)] == ["touchee"]
    conn = connect(s.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM notify_log WHERE event='touchee'").fetchone()[0] == 1
        assert len(list_zones(conn, tf=tf, min_score=4, statuses=["touchee"])) == 1
    finally:
        conn.close()


def test_vanished_untouched_zone_is_pruned_by_refresh(env):
    """Dropped from the scan for a detection reason (no touch, not expired) → deleted, but
    only after the lifecycle check; hidden from listings meanwhile."""
    from app.core.config import get_settings
    from app.core.store import connect, list_zones, upsert_zones

    s = get_settings()
    tf = "H1"
    df = _bars(tf)
    _write(s, "EURUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    zid = _rows(s, tf)[0]["id"]

    conn = connect(s.db_path)
    try:
        upsert_zones(conn, [], tf=tf, symbols={"EURUSD"})  # scan without it
        row = conn.execute("SELECT status, vanished_at FROM zones WHERE id=?", (zid,)).fetchone()
        assert row["status"] == "active" and row["vanished_at"]  # flagged, not deleted
        assert list_zones(conn, tf=tf, min_score=1) == []  # hidden like the old delete
        assert len(list_zones(conn, tf=tf, min_score=1, include_vanished=True)) == 1
    finally:
        conn.close()

    _, rs = _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None, drop=True)
    assert rs.vanished_pruned == 1 and _rows(s, tf) == [] and not env.sends


def test_vanished_zone_reappearing_is_unflagged(env):
    from app.core.config import get_settings
    from app.core.store import connect, upsert_zones

    s = get_settings()
    tf = "M15"
    _write(s, "EURUSD", tf, _bars(tf))
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    conn = connect(s.db_path)
    try:
        upsert_zones(conn, [], tf=tf, symbols={"EURUSD"})
    finally:
        conn.close()
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)  # detected again
    rows = _rows(s, tf)
    assert len(rows) == 1 and rows[0]["status"] == "active" and rows[0]["vanished_at"] is None


def test_vanished_expired_zone_is_kept_as_expiree(env):
    from app.core.config import get_settings

    s = get_settings()
    tf = "H4"
    df = _bars(tf)
    _write(s, "EURUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    # Price runs > 8 ATR away from the zone without touching it → expiry (distance)
    df2 = _append(df.iloc[:-1], tf, [(1.13, 1.21, 1.13, 1.20), (1.20, 1.21, 1.19, 1.20)])
    _write(s, "EURUSD", tf, df2)
    _, rs = _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None, drop=True)
    rows = _rows(s, tf)
    assert len(rows) == 1 and rows[0]["status"] == "expiree"
    assert rs.vanished_expired == 1 and not env.sends


def test_late_touch_older_than_armed_at_or_stale_is_silent(env):
    from app.core.config import get_settings

    s = get_settings()
    tf = "M5"
    step = pd.Timedelta(minutes=5)
    df = _bars(tf)
    touched = _append(df.iloc[:-1], tf, [(1.120, 1.122, 1.108, 1.115), (1.115, 1.118, 1.113, 1.116)])

    # (a) go-live guard: TF armed after the touch → no alert
    _write(s, "EURUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    _write(s, "EURUSD", tf, touched)
    armed_after = (NOW0 + step).timestamp()
    _, rs = _cycle(env, tf, now=(NOW0 + step).to_pydatetime(), notify_since=armed_after)
    assert _rows(s, tf)[0]["status"] == "touchee" and not env.sends

    # (b) staleness: same scenario on another symbol, refresh only runs 3 h later
    _write(s, "GBPUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None, symbols=("GBPUSD",))
    _write(s, "GBPUSD", tf, touched)
    _, rs = _cycle(env, tf, now=(NOW0 + pd.Timedelta(hours=3)).to_pydatetime(),
                   notify_since=None, symbols=("GBPUSD",))
    assert rs.vanished_touched == 1 and rs.stale_skipped == 1 and rs.notifications == 0
    assert not env.sends
    statuses = sorted(r["status"] for r in _rows(s, tf))
    assert statuses == ["touchee", "touchee"]  # still tracked for stats


def test_late_touch_respects_alert_tfs(env):
    from app.core.config import get_settings

    env.setenv("ALERT_TFS", "H1")
    get_settings.cache_clear()
    s = get_settings()
    tf = "M30"
    df = _bars(tf)
    _write(s, "EURUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    _write(s, "EURUSD", tf, _append(df.iloc[:-1], tf, [(1.12, 1.122, 1.108, 1.115), (1.115, 1.118, 1.113, 1.116)]))
    _cycle(env, tf, now=(NOW0 + pd.Timedelta(minutes=31)).to_pydatetime(), notify_since=None)
    assert _rows(s, tf)[0]["status"] == "touchee" and not env.sends


def test_failed_symbol_scan_does_not_flag_its_zones(env):
    from app.core.config import get_settings

    s = get_settings()
    tf = "H1"
    _write(s, "EURUSD", tf, _bars(tf))
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    import app.core.scanner as scanner

    def boom(*a, **k):
        raise RuntimeError("detector crashed")

    env.setattr(scanner, "detect_zones", boom)
    ss = scanner.run_scan(tfs=[tf], groups=["FOREX"], symbols=["EURUSD"], min_score=4, settings=s)
    assert not ss.per_symbol[0].ok
    assert _rows(s, tf)[0]["vanished_at"] is None


def test_late_touch_reaction_tracking_and_realistic_stats(env):
    """Late-detected H1 touch that fills at mid then runs to +2R: reaction tracked,
    realistic trade simulated, counted in stats."""
    from app.core.config import get_settings
    from app.core.monitor import compute_stats

    s = get_settings()
    tf = "H1"
    df = _bars(tf)
    _write(s, "EURUSD", tf, df)
    _cycle(env, tf, now=NOW0.to_pydatetime(), notify_since=None)
    # touch + fill at mid (low 1.104 ≤ entry 1.105) inside the bar, then +2R (1.125)
    df2 = _append(df.iloc[:-1], tf, [(1.112, 1.113, 1.104, 1.108), (1.108, 1.112, 1.107, 1.111)])
    _write(s, "EURUSD", tf, df2)
    _cycle(env, tf, now=(NOW0 + pd.Timedelta(minutes=61)).to_pydatetime(), notify_since=None)
    assert _rows(s, tf)[0]["status"] == "touchee" and len(env.sends) == 1
    df3 = _append(df2.iloc[:-1], tf, [(1.111, 1.126, 1.110, 1.124), (1.124, 1.125, 1.122, 1.123)])
    _write(s, "EURUSD", tf, df3)
    _, rs = _cycle(env, tf, now=(NOW0 + pd.Timedelta(minutes=121)).to_pydatetime(), notify_since=None)
    assert _rows(s, tf)[0]["status"] == "reaction" and len(env.sends) == 2  # touch + reaction
    st = compute_stats(tf=tf, settings=s)
    assert st["n_touched"] == 1 and st["n_reaction"] == 1
    real = st["realistic"]
    assert real["n_touched"] == 1 and real["n_unknown"] == 0  # trade sim ran on the zone


def test_alert_max_age_per_tf(env):
    from app.core.config import get_settings
    from app.core.monitor import alert_max_age_sec

    s = get_settings()
    got = {tf: alert_max_age_sec(tf, s) / 60 for tf in ALL_TFS}
    assert got == {"M5": 65, "M15": 75, "M30": 90, "H1": 135, "H4": 540, "D": 2880 + 120,
                   "W": 20160 + 360}
