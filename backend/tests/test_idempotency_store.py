import asyncio
from pathlib import Path

from backend.app.application.idempotency import (
    MemoryIdempotencyStore,
    PostgresIdempotencyStore,
)
from backend.app.core.errors import AppError


def test_memory_store_claims_replays_and_rejects_fingerprint_conflicts() -> None:
    async def run() -> None:
        store = MemoryIdempotencyStore()
        first = await store.claim("POST:/api/suites", "key-1", "a" * 64)
        await store.complete(
            "POST:/api/suites",
            "key-1",
            "a" * 64,
            response_status=201,
            response_body={"data": {"id": "suite-1"}},
        )
        replay = await store.claim("POST:/api/suites", "key-1", "a" * 64)

        assert first.is_owner is True
        assert replay.is_owner is False
        assert replay.record.status == "completed"
        assert replay.record.response_status == 201
        assert replay.record.response_body == {"data": {"id": "suite-1"}}

        try:
            await store.claim("POST:/api/suites", "key-1", "b" * 64)
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_KEY_CONFLICT"
            assert exc.status_code == 409
        else:
            raise AssertionError("相同幂等键不能绑定不同载荷")

    asyncio.run(run())


def test_postgres_adapter_exposes_persistent_claim_and_completion_operations() -> None:
    assert callable(PostgresIdempotencyStore.claim)
    assert callable(PostgresIdempotencyStore.complete)
    assert callable(PostgresIdempotencyStore.fail)
    assert callable(PostgresIdempotencyStore.get)


def test_idempotency_migration_has_fingerprint_status_response_and_scope_constraints() -> None:
    migration = Path(
        "alembic/versions/d4e5f6a7b8c9_expand_idempotency_records.py"
    ).read_text(encoding="utf-8")

    for required in (
        "request_fingerprint",
        "status",
        "response_status",
        "response_body",
        "updated_at",
        "PRIMARY KEY (scope, key)",
        "idempotency_status_check",
        "idempotency_fingerprint_check",
    ):
        assert required in migration
    assert 'down_revision = "c3d4e5f6a7b8"' in migration
