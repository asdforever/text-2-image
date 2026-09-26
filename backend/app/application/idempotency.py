"""幂等请求记录的内存与 PostgreSQL 适配器。"""

import json
import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ..core.errors import AppError


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def request_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    scope: str
    key: str
    request_fingerprint: str
    status: str
    response_status: int | None = None
    response_body: dict[str, Any] | None = None
    resource_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    is_owner: bool
    record: IdempotencyRecord


def _validate(scope: str, key: str, fingerprint: str) -> None:
    if not scope or not key or not _FINGERPRINT.fullmatch(fingerprint):
        raise AppError(
            "INVALID_IDEMPOTENCY_REQUEST",
            "idempotency scope, key or fingerprint is invalid",
            400,
        )


def _check_fingerprint(record: IdempotencyRecord, fingerprint: str) -> None:
    if record.request_fingerprint != fingerprint:
        raise AppError(
            "IDEMPOTENCY_KEY_CONFLICT",
            "idempotency key was already used for a different request",
            409,
        )


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}

    async def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        return self._records.get((scope, key))

    async def claim(
        self, scope: str, key: str, fingerprint: str, *, retry_failed: bool = False
    ) -> IdempotencyClaim:
        _validate(scope, key, fingerprint)
        existing = self._records.get((scope, key))
        if existing is not None:
            _check_fingerprint(existing, fingerprint)
            if not (retry_failed and existing.status == "failed"):
                return IdempotencyClaim(False, existing)
        record = IdempotencyRecord(scope, key, fingerprint, "in_progress")
        self._records[(scope, key)] = record
        return IdempotencyClaim(True, record)

    async def complete(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        *,
        response_status: int,
        response_body: dict[str, Any],
        resource_id: UUID | None = None,
    ) -> IdempotencyRecord:
        existing = self._records.get((scope, key))
        if existing is None:
            raise AppError("IDEMPOTENCY_RECORD_NOT_FOUND", "idempotency record is missing", 409)
        _check_fingerprint(existing, fingerprint)
        record = IdempotencyRecord(
            scope,
            key,
            fingerprint,
            "completed",
            response_status,
            response_body,
            resource_id,
        )
        self._records[(scope, key)] = record
        return record

    async def fail(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        *,
        response_status: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        record = await self.complete(
            scope,
            key,
            fingerprint,
            response_status=response_status,
            response_body=response_body,
        )
        failed = IdempotencyRecord(
            record.scope,
            record.key,
            record.request_fingerprint,
            "failed",
            record.response_status,
            record.response_body,
            record.resource_id,
        )
        self._records[(scope, key)] = failed
        return failed


class PostgresIdempotencyStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _record(row) -> IdempotencyRecord:
        body = row["response_body"]
        if isinstance(body, str):
            body = json.loads(body)
        return IdempotencyRecord(
            scope=row["scope"],
            key=row["key"],
            request_fingerprint=row["request_fingerprint"],
            status=row["status"],
            response_status=row["response_status"],
            response_body=body,
            resource_id=row["resource_id"],
        )

    async def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT scope,key,request_fingerprint,status,response_status,"
                    "response_body,resource_id FROM suite_workbench.idempotency_keys "
                    "WHERE scope=:scope AND key=:key"
                ),
                {"scope": scope, "key": key},
            )
            row = result.mappings().first()
            return self._record(row) if row else None

    async def claim(
        self, scope: str, key: str, fingerprint: str, *, retry_failed: bool = False
    ) -> IdempotencyClaim:
        _validate(scope, key, fingerprint)
        async with self.session_factory() as session, session.begin():
            inserted = await session.execute(
                text(
                    "INSERT INTO suite_workbench.idempotency_keys "
                    "(scope,key,request_fingerprint,status) "
                    "VALUES (:scope,:key,:fingerprint,'in_progress') "
                    "ON CONFLICT (scope,key) DO NOTHING "
                    "RETURNING scope,key,request_fingerprint,status,response_status,"
                    "response_body,resource_id"
                ),
                {"scope": scope, "key": key, "fingerprint": fingerprint},
            )
            row = inserted.mappings().first()
            if row:
                return IdempotencyClaim(True, self._record(row))
            existing = await session.execute(
                text(
                    "SELECT scope,key,request_fingerprint,status,response_status,"
                    "response_body,resource_id FROM suite_workbench.idempotency_keys "
                    "WHERE scope=:scope AND key=:key FOR UPDATE"
                ),
                {"scope": scope, "key": key},
            )
            record = self._record(existing.mappings().one())
            _check_fingerprint(record, fingerprint)
            if retry_failed and record.status == "failed":
                await session.execute(text("UPDATE suite_workbench.idempotency_keys SET status='in_progress', response_status=NULL, response_body=NULL, updated_at=now() WHERE scope=:scope AND key=:key"), {"scope": scope, "key": key})
                return IdempotencyClaim(True, IdempotencyRecord(scope, key, fingerprint, "in_progress", None, None, record.resource_id))
            return IdempotencyClaim(False, record)

    async def complete(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        *,
        response_status: int,
        response_body: dict[str, Any],
        resource_id: UUID | None = None,
    ) -> IdempotencyRecord:
        return await self._finish(
            scope,
            key,
            fingerprint,
            "completed",
            response_status,
            response_body,
            resource_id,
        )

    async def fail(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        *,
        response_status: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        return await self._finish(
            scope,
            key,
            fingerprint,
            "failed",
            response_status,
            response_body,
            None,
        )

    async def _finish(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        status: str,
        response_status: int,
        response_body: dict[str, Any],
        resource_id: UUID | None,
    ) -> IdempotencyRecord:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE suite_workbench.idempotency_keys SET status=:status,"
                    "response_status=:response_status,response_body=CAST(:response_body AS jsonb),"
                    "resource_id=COALESCE(:resource_id,resource_id),updated_at=now() "
                    "WHERE scope=:scope AND key=:key AND request_fingerprint=:fingerprint "
                    "RETURNING scope,key,request_fingerprint,status,response_status,"
                    "response_body,resource_id"
                ),
                {
                    "scope": scope,
                    "key": key,
                    "fingerprint": fingerprint,
                    "status": status,
                    "response_status": response_status,
                    "response_body": json.dumps(response_body),
                    "resource_id": resource_id,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise AppError(
                    "IDEMPOTENCY_RECORD_NOT_FOUND",
                    "idempotency record is missing or does not match",
                    409,
                )
            return self._record(row)
