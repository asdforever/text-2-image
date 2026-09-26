import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.generation_worker_health import MemoryWorkerHealth, keep_worker_alive


@pytest.mark.asyncio
async def test_only_fresh_workers_are_online_and_shutdown_is_per_instance():
    health = MemoryWorkerHealth()
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    assert (await health.status(now=now))["status"] == "offline"
    await health.beat("first", now=now)
    await health.beat("second", now=now + timedelta(seconds=30))
    assert (await health.status(now=now + timedelta(seconds=50)))["status"] == "online"
    await health.remove("first")
    assert (await health.status(now=now + timedelta(seconds=50)))["status"] == "online"
    assert (await health.status(now=now + timedelta(seconds=76)))["status"] == "offline"
    await health.remove("second")
    assert (await health.status(now=now))["status"] == "offline"


@pytest.mark.asyncio
async def test_heartbeat_continues_during_long_generation_and_cleans_up():
    health = MemoryWorkerHealth()
    async with keep_worker_alive(health, "worker", interval=.01):
        first = (await health.status())["lastSeenAt"]
        await asyncio.sleep(.04)
        status = await health.status()
        assert status["status"] == "online"
        assert status["lastSeenAt"] > first
    assert (await health.status())["status"] == "offline"


@pytest.mark.asyncio
async def test_worker_exception_clears_its_heartbeat():
    health = MemoryWorkerHealth()
    with pytest.raises(RuntimeError):
        async with keep_worker_alive(health, "worker"):
            raise RuntimeError("队列执行失败")
    assert (await health.status())["status"] == "offline"


def test_health_endpoint_reports_offline_online_and_unknown_without_affecting_api():
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    from backend.app.core.config import Settings

    app = create_app(settings=Settings(_env_file=None, database_url=None, pg_host=None, minio_endpoint=None))
    with TestClient(app) as client:
        assert client.get("/api/generation-worker/status").json()["data"]["status"] == "offline"
        app.state.generation_worker_health.workers["worker"] = datetime.now(timezone.utc)
        assert client.get("/api/generation-worker/status").json()["data"]["status"] == "online"

        class Unavailable:
            async def status(self):
                raise RuntimeError("数据库不可用")

        app.state.generation_worker_health = Unavailable()
        assert client.get("/api/generation-worker/status").json()["data"]["status"] == "unknown"
        assert client.get("/api/health").status_code == 200


@pytest.mark.asyncio
async def test_postgres_heartbeat_is_visible_across_repositories_and_removal_is_scoped():
    from uuid import uuid4
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from backend.app.core.config import get_settings
    from backend.app.db import create_engine
    from backend.app.generation_worker_health import PostgresWorkerHealth

    url = get_settings().database_url
    if not url:
        pytest.skip("未配置 PostgreSQL")
    engine = create_engine(url)
    first, second = str(uuid4()), str(uuid4())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                sessions = async_sessionmaker(connection, join_transaction_mode="create_savepoint")
                writer, reader = PostgresWorkerHealth(sessions), PostgresWorkerHealth(sessions)
                await writer.beat(first)
                await writer.beat(second)
                assert (await reader.status())["status"] == "online"
                await writer.remove(first)
                assert await connection.scalar(text("SELECT count(*) FROM project_workbench.generation_worker_heartbeats WHERE worker_id=:id"), {"id": first}) == 0
                assert await connection.scalar(text("SELECT count(*) FROM project_workbench.generation_worker_heartbeats WHERE worker_id=:id"), {"id": second}) == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
