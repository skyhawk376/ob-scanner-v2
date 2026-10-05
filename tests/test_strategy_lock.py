"""Filtre B hard lock: groups METAUX/FOREX/CRYPTO, >=4★."""
from app.core.config import Settings


def _s(**kw):
    return Settings(default_scan_groups="METAUX,FOREX,CRYPTO", default_min_score=4, **kw)


def test_clamp_groups_locked():
    s = _s(strategy_lock=True)
    assert s.clamp_groups(None) == ["METAUX", "FOREX", "CRYPTO"]
    assert s.clamp_groups("ALL") == ["METAUX", "FOREX", "CRYPTO"]
    assert s.clamp_groups("METAUX,NQ100,ENERGIE") == ["METAUX"]
    assert s.clamp_groups("NQ100") == []


def test_clamp_min_score_locked():
    s = _s(strategy_lock=True)
    assert s.clamp_min_score(1) == 4
    assert s.clamp_min_score(5) == 5


def test_zone_in_strategy():
    s = _s(strategy_lock=True)
    assert s.zone_in_strategy("FOREX", 4)
    assert not s.zone_in_strategy("FOREX", 3)
    assert not s.zone_in_strategy("NQ100", 5)
    assert not s.zone_in_strategy("ENERGIE", 5)


def test_unlocked_is_permissive():
    s = _s(strategy_lock=False)
    assert s.clamp_groups("ALL") is None
    assert s.clamp_min_score(1) == 1
    assert s.zone_in_strategy("NQ100", 1)
