import asyncio

import pytest

from backend.app.migration_guard import (
    MigrationDriftError,
    run_guarded_migration,
)


class _GuardConnection:
    def __init__(self, lock: asyncio.Lock, rows=None) -> None:
        self.lock = lock
        self.rows = rows or []
        self.recorded = []

    async def execute(self, query, *args):
        if "pg_advisory_lock" in query and "unlock" not in query:
            await self.lock.acquire()
        elif "pg_advisory_unlock" in query:
            self.lock.release()

    async def fetch(self, query):
        return self.rows

    async def executemany(self, query, values):
        self.recorded.extend(values)


def test_checksum_drift_stops_before_running_new_migrations() -> None:
    async def run() -> None:
        connection = _GuardConnection(
            asyncio.Lock(),
            rows=[{"revision": "0001_initial", "checksum": "old"}],
        )
        called = False

        async def migrate():
            nonlocal called
            called = True

        with pytest.raises(MigrationDriftError):
            await run_guarded_migration(
                connection,
                {"0001_initial": "new"},
                migrate,
                checksum_table_exists=True,
            )
        assert called is False

    asyncio.run(run())


def test_concurrent_migration_attempts_are_serialized_by_database_lock() -> None:
    async def run() -> None:
        lock = asyncio.Lock()
        events: list[str] = []

        async def invoke(name: str):
            connection = _GuardConnection(lock)

            async def migrate():
                events.append(f"{name}:start")
                await asyncio.sleep(0)
                events.append(f"{name}:end")

            await run_guarded_migration(
                connection,
                {"head": "a" * 64},
                migrate,
                checksum_table_exists=False,
            )

        await asyncio.gather(invoke("one"), invoke("two"))
        assert events in (
            ["one:start", "one:end", "two:start", "two:end"],
            ["two:start", "two:end", "one:start", "one:end"],
        )

    asyncio.run(run())
