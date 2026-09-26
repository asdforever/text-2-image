import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend import cli
from backend.app.generation_worker_health import MemoryWorkerHealth, keep_worker_alive


@pytest.mark.parametrize("failure_phase", ["recover", "claim"])
def test_worker_survives_iteration_errors_keeps_heartbeat_and_resumes(monkeypatch, failure_phase):
    health = MemoryWorkerHealth()
    recovered = 0
    attempts = 0
    successes = []
    pauses = []
    heartbeats = []
    real_sleep = asyncio.sleep

    async def recover():
        nonlocal recovered
        recovered += 1
        if failure_phase == "recover" and recovered == 1:
            raise RuntimeError("temporary database outage")

    async def run_once(*, limit, raise_on_error, refill, poll_interval):
        assert not raise_on_error
        assert refill
        nonlocal attempts
        attempts += 1
        if failure_phase == "claim" and attempts == 1:
            raise RuntimeError("temporary claim failure")
        status = await health.status()
        assert status["status"] == "online"
        heartbeats.append(status["lastSeenAt"])
        if len(successes) == 2:
            raise asyncio.CancelledError()
        successes.append(limit)
        return 0

    async def pause(delay):
        pauses.append(delay)
        await real_sleep(.005)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = SimpleNamespace(
        router=SimpleNamespace(lifespan_context=lifespan),
        state=SimpleNamespace(
            settings=SimpleNamespace(generation_worker_lease_seconds=60, generation_worker_concurrency=1,
                                     generation_worker_claim_limit=4, generation_worker_poll_interval_ms=1),
            batch_generation_repository=SimpleNamespace(recover_expired_leases=recover),
            generation_worker_health=health,
            project_repository=None, project_asset_storage=None, project_asset_service=None,
            hero_generation_service=SimpleNamespace(image_editor=None), product_library_service=None,
        ),
    )
    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(cli, "BatchGenerationWorker", lambda **kwargs: SimpleNamespace(run_once=run_once))
    monkeypatch.setattr(cli, "keep_worker_alive", lambda health, worker_id: keep_worker_alive(health, worker_id, interval=.001))
    monkeypatch.setattr(cli.asyncio, "sleep", pause)

    with pytest.raises(asyncio.CancelledError):
        cli.generation_worker(False)

    assert successes == [4, 4]
    assert heartbeats[-1] > heartbeats[0]
    assert pauses and all(delay > 0 for delay in pauses)
    assert not health.workers


def test_once_mode_still_reports_failure(monkeypatch):
    @asynccontextmanager
    async def lifespan(app):
        yield

    async def recover():
        raise RuntimeError("database unavailable")

    state = SimpleNamespace(
        settings=SimpleNamespace(generation_worker_lease_seconds=60, generation_worker_concurrency=1),
        batch_generation_repository=SimpleNamespace(recover_expired_leases=recover),
        generation_worker_health=MemoryWorkerHealth(), project_repository=None,
        project_asset_storage=None, project_asset_service=None,
        hero_generation_service=SimpleNamespace(image_editor=None), product_library_service=None,
    )
    monkeypatch.setattr(cli, "create_app", lambda: SimpleNamespace(state=state, router=SimpleNamespace(lifespan_context=lifespan)))
    with pytest.raises(RuntimeError, match="database unavailable"):
        cli.generation_worker(True)
    assert not state.generation_worker_health.workers
