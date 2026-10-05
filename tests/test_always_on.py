"""Always-on host wiring: /healthz, /fetch gating, pipeline lock + status file."""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.api.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_has_pipeline_block(client):
    d = client.get("/health").json()
    assert "pipeline" in d and "cache_stale" in d and "scheduler_info" in d


def test_fetch_disabled_returns_501(client, monkeypatch):
    monkeypatch.setenv("ENABLE_FETCH", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert client.post("/fetch?tf=H1").status_code == 501


def test_fetch_background_starts_pipeline(client, monkeypatch):
    import app.core.jobs as jobs

    calls = {}
    monkeypatch.setattr(jobs, "start_pipeline_thread", lambda **kw: calls.update(kw) or True)
    r = client.post("/fetch?tf=H1&limit=100")
    assert r.status_code == 202
    assert calls["tfs"] == ["H1"] and calls["limit"] == 100


def test_pipeline_lock_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.core.fetcher as fetcher
    import app.core.jobs as jobs

    gate = threading.Event()
    release = threading.Event()

    class _Sum:
        ok_count, fail_count, elapsed_sec, results = 1, 0, 0.1, []

        def by_source(self):
            return {"test": {"ok": 1, "fail": 0}}

    def fake_fetch_all(**kw):
        gate.set()
        release.wait(5)
        return _Sum()

    monkeypatch.setattr(fetcher, "fetch_all", fake_fetch_all)
    t = threading.Thread(target=lambda: jobs.run_pipeline(scan=False, refresh=False, trigger="t1"))
    t.start()
    assert gate.wait(5)
    second = jobs.run_pipeline(scan=False, refresh=False, trigger="t2")
    assert second.get("skipped") is True
    release.set()
    t.join(5)
    st = jobs.read_status()
    assert st["running"] is False
    assert st["last"]["ok"] is True and st["last"]["trigger"] == "t1"
    assert st["last"]["steps"]["fetch"]["ok"] == 1
    get_settings.cache_clear()
