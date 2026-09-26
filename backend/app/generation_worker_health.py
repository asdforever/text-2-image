"""执行器独立心跳；耗时生图期间仍更新，接口不以等待时长猜测离线。"""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import text

TTL_SECONDS = 45
logger = logging.getLogger(__name__)


def _status(last_seen, now):
    return {
        "status": "online" if last_seen and last_seen > now - timedelta(seconds=TTL_SECONDS) else "offline",
        "lastSeenAt": last_seen.isoformat() if last_seen else None,
    }


class MemoryWorkerHealth:
    def __init__(self):
        self.workers = {}

    async def beat(self, worker_id, *, now=None):
        self.workers[worker_id] = now or datetime.now(timezone.utc)

    async def remove(self, worker_id):
        self.workers.pop(worker_id, None)

    async def status(self, *, now=None):
        return _status(max(self.workers.values(), default=None), now or datetime.now(timezone.utc))


class PostgresWorkerHealth:
    def __init__(self, sessions):
        self.sessions = sessions

    async def beat(self, worker_id):
        async with self.sessions() as session, session.begin():
            await session.execute(text(
                "INSERT INTO project_workbench.generation_worker_heartbeats(worker_id,last_seen_at) "
                "VALUES (:id, now()) ON CONFLICT(worker_id) DO UPDATE SET last_seen_at=now()"
            ), {"id": worker_id})
            await session.execute(text("DELETE FROM project_workbench.generation_worker_heartbeats WHERE last_seen_at < now() - interval '1 day'"))

    async def remove(self, worker_id):
        async with self.sessions() as session, session.begin():
            await session.execute(text("DELETE FROM project_workbench.generation_worker_heartbeats WHERE worker_id=:id"), {"id": worker_id})

    async def status(self):
        async with self.sessions() as session:
            row = (await session.execute(text(
                "SELECT max(last_seen_at) AS last_seen, now() AS current_time FROM project_workbench.generation_worker_heartbeats"
            ))).mappings().one()
            return _status(row["last_seen"], row["current_time"])


@asynccontextmanager
async def keep_worker_alive(health, worker_id, *, interval=10):
    async def beat():
        try:
            await health.beat(worker_id)
        except Exception:
            # 心跳异常不能中断已经发送的生图请求；接口会显示未知或心跳过期。
            logger.warning("生图执行器心跳更新失败，请检查数据库及迁移状态")

    async def loop():
        while True:
            await asyncio.sleep(interval)
            await beat()

    await beat()
    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        try:
            await health.remove(worker_id)
        except Exception:
            logger.warning("生图执行器心跳清理失败，将在超时后失效")
