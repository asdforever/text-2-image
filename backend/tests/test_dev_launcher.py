from unittest.mock import Mock
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend import dev
from backend import cli
from backend.app.generation_worker_health import MemoryWorkerHealth


def process(exit_code=None):
    result = Mock()
    result.poll.return_value = exit_code
    return result


def test_api_failure_does_not_start_generation_worker(monkeypatch):
    api = process(1)
    spawn = Mock(return_value=api)
    monkeypatch.setattr(dev.subprocess, "Popen", spawn)
    monkeypatch.setattr(dev, "wait_ready", lambda api, port: (_ for _ in ()).throw(RuntimeError("接口启动失败")))
    with pytest.raises(RuntimeError, match="接口启动失败"):
        dev.run_services(port=8000)
    assert spawn.call_count == 1


def test_worker_failure_stops_api_and_reports_nonzero_exit(monkeypatch):
    api, worker = process(), process(3)
    spawn = Mock(side_effect=[api, worker])
    monkeypatch.setattr(dev.subprocess, "Popen", spawn)
    monkeypatch.setattr(dev, "wait_ready", lambda api, port: None)
    assert dev.run_services(port=8000) == 3
    assert "uvicorn" in spawn.call_args_list[0].args[0]
    assert spawn.call_args_list[1].args[0][-2:] == ["backend.cli", "generation-worker"]
    api.terminate.assert_called_once()
    api.wait.assert_called_once()


def test_interrupt_stops_both_owned_processes(monkeypatch):
    api, worker = process(), process()
    monkeypatch.setattr(dev.subprocess, "Popen", Mock(side_effect=[api,worker]))
    monkeypatch.setattr(dev, "wait_ready", lambda api, port: None)
    monkeypatch.setattr(dev.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    assert dev.run_services(port=8000) == 0
    api.terminate.assert_called_once()
    worker.terminate.assert_called_once()


def test_generation_loop_retries_transient_queue_failure_before_processing(monkeypatch):
    class Repository:
        def __init__(self):
            self.recoveries = 0

        async def recover_expired_leases(self):
            self.recoveries += 1
            if self.recoveries == 1:
                raise OSError("database connection dropped")

    class Worker:
        def __init__(self):
            self.calls = 0

        async def run_once(self, *, limit, raise_on_error, refill, poll_interval):
            self.calls += 1
            raise asyncio.CancelledError()

    class Settings:
        generation_worker_claim_limit = 1
        generation_worker_poll_interval_ms = 100
        generation_worker_lease_seconds = 60
        generation_worker_concurrency = 1

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    repository = Repository()
    worker = Worker()
    @asynccontextmanager
    async def lifespan(app):
        yield

    app = SimpleNamespace(
        router=SimpleNamespace(lifespan_context=lifespan),
        state=SimpleNamespace(
            settings=Settings(), batch_generation_repository=repository,
            generation_worker_health=MemoryWorkerHealth(),
            project_repository=None, project_asset_storage=None, project_asset_service=None,
            hero_generation_service=SimpleNamespace(image_editor=None), product_library_service=None,
        ),
    )
    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(cli, "BatchGenerationWorker", lambda **kwargs: worker)
    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        cli.generation_worker(False)

    assert repository.recoveries == 2
    assert worker.calls == 1
    assert sleeps == [1.0]
