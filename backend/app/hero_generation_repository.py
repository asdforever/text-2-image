from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


@dataclass
class HeroGenerationTaskRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    source_asset_id: UUID
    status: str
    compile_idempotency_key: str
    compile_fingerprint: str
    snapshot: dict[str, Any]
    confirm_idempotency_key: str | None = None
    confirm_fingerprint: str | None = None
    compiled_task_prompt: str | None = None
    compiler_output: dict[str, Any] | None = None
    confirmed_task_prompt: str | None = None
    final_prompt: str | None = None
    final_prompt_sha256: str | None = None
    provider_request: dict[str, Any] | None = None
    generated_asset_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None


class InMemoryHeroGenerationRepository:
    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        state = backing_store if backing_store is not None else {}
        self._tasks: dict[UUID, HeroGenerationTaskRecord] = state.setdefault(
            "hero_generation_tasks", {}
        )

    async def create_compiling(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_asset_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
    ) -> tuple[HeroGenerationTaskRecord, bool]:
        existing = next(
            (
                task
                for task in self._tasks.values()
                if task.workspace_id == workspace_id
                and task.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        if existing is not None:
            _same_fingerprint(existing.compile_fingerprint, fingerprint)
            return _copy(existing), True
        now = datetime.now(timezone.utc)
        task = HeroGenerationTaskRecord(
            uuid4(),
            workspace_id,
            project_id,
            source_asset_id,
            "compiling_prompt",
            idempotency_key,
            fingerprint,
            deepcopy(snapshot),
            created_at=now,
            updated_at=now,
        )
        self._tasks[task.id] = task
        return _copy(task), False

    async def get_task(
        self, task_id: UUID, workspace_id: UUID
    ) -> HeroGenerationTaskRecord | None:
        task = self._tasks.get(task_id)
        return _copy(task) if task is not None and task.workspace_id == workspace_id else None

    async def get_latest(self, project_id: UUID, workspace_id: UUID) -> HeroGenerationTaskRecord | None:
        candidates = [
            task for task in self._tasks.values()
            if task.project_id == project_id and task.workspace_id == workspace_id
        ]
        return _copy(max(candidates, key=lambda item: (item.updated_at, str(item.id)))) if candidates else None

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> HeroGenerationTaskRecord | None:
        task = next(
            (
                item
                for item in self._tasks.values()
                if item.workspace_id == workspace_id
                and item.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        return _copy(task) if task is not None else None

    async def save_planning_snapshot(self, task_id: UUID, workspace_id: UUID, snapshot: dict) -> None:
        task = self._required(task_id, workspace_id)
        _require_status(task, "compiling_prompt")
        task.snapshot = deepcopy(snapshot)

    async def mark_awaiting_confirmation(
        self,
        task_id: UUID,
        workspace_id: UUID,
        *,
        compiled_task_prompt: str,
        compiler_output: dict[str, Any],
    ) -> HeroGenerationTaskRecord:
        task = self._required(task_id, workspace_id)
        _require_status(task, "compiling_prompt")
        task.status = "awaiting_confirmation"
        task.compiled_task_prompt = compiled_task_prompt
        task.compiler_output = deepcopy(compiler_output)
        task.updated_at = datetime.now(timezone.utc)
        return _copy(task)

    async def begin_confirmation(
        self,
        task_id: UUID,
        workspace_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        *,
        confirmed_task_prompt: str,
        final_prompt: str,
        final_prompt_sha256: str,
        provider_request: dict[str, Any],
    ) -> tuple[HeroGenerationTaskRecord, bool]:
        task = self._required(task_id, workspace_id)
        if task.confirm_idempotency_key == idempotency_key:
            _same_fingerprint(task.confirm_fingerprint or "", fingerprint)
            return _copy(task), True
        conflicting = next(
            (
                item
                for item in self._tasks.values()
                if item.workspace_id == workspace_id
                and item.confirm_idempotency_key == idempotency_key
            ),
            None,
        )
        if conflicting is not None:
            raise AppError(
                "IDEMPOTENCY_KEY_REUSED",
                "idempotency key was already used for a different request",
                409,
            )
        _require_status(task, "awaiting_confirmation")
        now = datetime.now(timezone.utc)
        task.status = "generating"
        task.confirm_idempotency_key = idempotency_key
        task.confirm_fingerprint = fingerprint
        task.confirmed_task_prompt = confirmed_task_prompt
        task.final_prompt = final_prompt
        task.final_prompt_sha256 = final_prompt_sha256
        task.provider_request = deepcopy(provider_request)
        task.confirmed_at = now
        task.updated_at = now
        return _copy(task), False

    async def complete(
        self, task_id: UUID, workspace_id: UUID, generated_asset_id: UUID
    ) -> HeroGenerationTaskRecord:
        task = self._required(task_id, workspace_id)
        _require_status(task, "generating")
        now = datetime.now(timezone.utc)
        task.status = "succeeded"
        task.generated_asset_id = generated_asset_id
        task.completed_at = now
        task.updated_at = now
        return _copy(task)

    async def fail(
        self, task_id: UUID, workspace_id: UUID, code: str, message: str
    ) -> HeroGenerationTaskRecord:
        task = self._required(task_id, workspace_id)
        if task.status == "succeeded":
            _invalid_state()
        now = datetime.now(timezone.utc)
        task.status = "failed"
        task.error_code = code
        task.error_message = message
        task.completed_at = now
        task.updated_at = now
        return _copy(task)

    async def ready(self) -> bool:
        return True

    def _required(self, task_id: UUID, workspace_id: UUID) -> HeroGenerationTaskRecord:
        task = self._tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise AppError("HERO_GENERATION_NOT_FOUND", "hero generation task does not exist", 404)
        return task


class PostgresHeroGenerationRepository:
    async def save_planning_snapshot(self, task_id: UUID, workspace_id: UUID, snapshot: dict) -> None:
        async with self.sessions() as session, session.begin():
            result = await session.execute(text(
                "UPDATE project_workbench.hero_generation_tasks SET snapshot=CAST(:snapshot AS jsonb), updated_at=now() "
                "WHERE id=:id AND workspace_id=:workspace_id AND status='compiling_prompt' RETURNING id"
            ), {"id": task_id, "workspace_id": workspace_id, "snapshot": json.dumps(snapshot, ensure_ascii=False)})
            if result.scalar_one_or_none() is None:
                raise AppError("HERO_GENERATION_INVALID_STATE", "主图任务状态无效", 409)

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_compiling(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_asset_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
    ) -> tuple[HeroGenerationTaskRecord, bool]:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.hero_generation_tasks "
                    "(id, workspace_id, project_id, source_asset_id, compile_idempotency_key, "
                    "compile_fingerprint, snapshot) VALUES (:id, :workspace_id, :project_id, "
                    ":source_asset_id, :key, :fingerprint, CAST(:snapshot AS jsonb)) "
                    "ON CONFLICT (workspace_id, compile_idempotency_key) DO NOTHING "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "source_asset_id": source_asset_id,
                    "key": idempotency_key,
                    "fingerprint": fingerprint,
                    "snapshot": json.dumps(snapshot, ensure_ascii=False),
                },
            )
            result = row.mappings().first()
            if result is not None:
                return _from_row(result), False
            existing = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM project_workbench.hero_generation_tasks "
                    "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            task = _from_row(existing.mappings().one())
            _same_fingerprint(task.compile_fingerprint, fingerprint)
            return task, True

    async def get_task(
        self, task_id: UUID, workspace_id: UUID
    ) -> HeroGenerationTaskRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM project_workbench.hero_generation_tasks "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": task_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _from_row(result) if result is not None else None

    async def get_latest(self, project_id: UUID, workspace_id: UUID) -> HeroGenerationTaskRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM project_workbench.hero_generation_tasks "
                    "WHERE project_id=:project_id AND workspace_id=:workspace_id "
                    "ORDER BY updated_at DESC, id DESC LIMIT 1"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _from_row(result) if result is not None else None

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> HeroGenerationTaskRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM project_workbench.hero_generation_tasks "
                    "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            result = row.mappings().first()
            return _from_row(result) if result is not None else None

    async def mark_awaiting_confirmation(
        self,
        task_id: UUID,
        workspace_id: UUID,
        *,
        compiled_task_prompt: str,
        compiler_output: dict[str, Any],
    ) -> HeroGenerationTaskRecord:
        return await self._transition(
            task_id,
            workspace_id,
            "compiling_prompt",
            "awaiting_confirmation",
            "compiled_task_prompt=:compiled_task_prompt, compiler_output=CAST(:compiler_output AS jsonb)",
            {
                "compiled_task_prompt": compiled_task_prompt,
                "compiler_output": json.dumps(compiler_output, ensure_ascii=False),
            },
        )

    async def begin_confirmation(
        self,
        task_id: UUID,
        workspace_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        *,
        confirmed_task_prompt: str,
        final_prompt: str,
        final_prompt_sha256: str,
        provider_request: dict[str, Any],
    ) -> tuple[HeroGenerationTaskRecord, bool]:
        async with self.sessions() as session, session.begin():
            current_row = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM project_workbench.hero_generation_tasks "
                    "WHERE id=:id AND workspace_id=:workspace_id FOR UPDATE"
                ),
                {"id": task_id, "workspace_id": workspace_id},
            )
            current_data = current_row.mappings().first()
            if current_data is None:
                raise AppError("HERO_GENERATION_NOT_FOUND", "hero generation task does not exist", 404)
            current = _from_row(current_data)
            if current.confirm_idempotency_key == idempotency_key:
                _same_fingerprint(current.confirm_fingerprint or "", fingerprint)
                return current, True
            if current.status != "awaiting_confirmation":
                _invalid_state()
            duplicate_key = await session.scalar(
                text(
                    "SELECT id FROM project_workbench.hero_generation_tasks "
                    "WHERE workspace_id=:workspace_id AND confirm_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            if duplicate_key is not None:
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "idempotency key was already used for a different request",
                    409,
                )
            row = await session.execute(
                text(
                    "UPDATE project_workbench.hero_generation_tasks SET status='generating', "
                    "confirm_idempotency_key=:key, confirm_fingerprint=:fingerprint, "
                    "confirmed_task_prompt=:confirmed_task_prompt, final_prompt=:final_prompt, "
                    "final_prompt_sha256=:final_prompt_sha256, "
                    "provider_request=CAST(:provider_request AS jsonb), confirmed_at=now(), "
                    f"updated_at=now() WHERE id=:id RETURNING {_COLUMNS}"
                ),
                {
                    "id": task_id,
                    "key": idempotency_key,
                    "fingerprint": fingerprint,
                    "confirmed_task_prompt": confirmed_task_prompt,
                    "final_prompt": final_prompt,
                    "final_prompt_sha256": final_prompt_sha256,
                    "provider_request": json.dumps(provider_request, ensure_ascii=False),
                },
            )
            return _from_row(row.mappings().one()), False

    async def complete(
        self, task_id: UUID, workspace_id: UUID, generated_asset_id: UUID
    ) -> HeroGenerationTaskRecord:
        return await self._transition(
            task_id,
            workspace_id,
            "generating",
            "succeeded",
            "generated_asset_id=:generated_asset_id, completed_at=now()",
            {"generated_asset_id": generated_asset_id},
        )

    async def fail(
        self, task_id: UUID, workspace_id: UUID, code: str, message: str
    ) -> HeroGenerationTaskRecord:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.hero_generation_tasks SET status='failed', "
                    "error_code=:code, error_message=:message, completed_at=now(), updated_at=now() "
                    "WHERE id=:id AND workspace_id=:workspace_id AND status <> 'succeeded' "
                    f"RETURNING {_COLUMNS}"
                ),
                {"id": task_id, "workspace_id": workspace_id, "code": code, "message": message},
            )
            result = row.mappings().first()
            if result is None:
                await self._raise_missing_or_state(session, task_id, workspace_id)
            return _from_row(result)

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(
                    await session.scalar(
                        text(
                            "SELECT to_regclass('project_workbench.hero_generation_tasks') IS NOT NULL"
                        )
                    )
                )
        except Exception:
            return False

    async def _transition(
        self,
        task_id: UUID,
        workspace_id: UUID,
        expected: str,
        target: str,
        assignments: str,
        values: dict[str, Any],
    ) -> HeroGenerationTaskRecord:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    f"UPDATE project_workbench.hero_generation_tasks SET status=:target, {assignments}, "
                    "updated_at=now() WHERE id=:id AND workspace_id=:workspace_id AND status=:expected "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": task_id,
                    "workspace_id": workspace_id,
                    "expected": expected,
                    "target": target,
                    **values,
                },
            )
            result = row.mappings().first()
            if result is None:
                await self._raise_missing_or_state(session, task_id, workspace_id)
            return _from_row(result)

    @staticmethod
    async def _raise_missing_or_state(
        session: AsyncSession, task_id: UUID, workspace_id: UUID
    ) -> None:
        exists = await session.scalar(
            text(
                "SELECT 1 FROM project_workbench.hero_generation_tasks "
                "WHERE id=:id AND workspace_id=:workspace_id"
            ),
            {"id": task_id, "workspace_id": workspace_id},
        )
        if not exists:
            raise AppError("HERO_GENERATION_NOT_FOUND", "hero generation task does not exist", 404)
        _invalid_state()


_COLUMNS = (
    "id, workspace_id, project_id, source_asset_id, status, compile_idempotency_key, "
    "compile_fingerprint, confirm_idempotency_key, confirm_fingerprint, snapshot, "
    "compiled_task_prompt, compiler_output, confirmed_task_prompt, final_prompt, "
    "final_prompt_sha256, provider_request, generated_asset_id, error_code, error_message, "
    "created_at, updated_at, confirmed_at, completed_at"
)


def _from_row(row: Any) -> HeroGenerationTaskRecord:
    return HeroGenerationTaskRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        source_asset_id=row["source_asset_id"],
        status=row["status"],
        compile_idempotency_key=row["compile_idempotency_key"],
        compile_fingerprint=row["compile_fingerprint"],
        snapshot=deepcopy(row["snapshot"]),
        confirm_idempotency_key=row["confirm_idempotency_key"],
        confirm_fingerprint=row["confirm_fingerprint"],
        compiled_task_prompt=row["compiled_task_prompt"],
        compiler_output=deepcopy(row["compiler_output"]),
        confirmed_task_prompt=row["confirmed_task_prompt"],
        final_prompt=row["final_prompt"],
        final_prompt_sha256=row["final_prompt_sha256"],
        provider_request=deepcopy(row["provider_request"]),
        generated_asset_id=row["generated_asset_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        confirmed_at=row["confirmed_at"],
        completed_at=row["completed_at"],
    )


def _copy(task: HeroGenerationTaskRecord) -> HeroGenerationTaskRecord:
    copied = deepcopy(task)
    return copied


def _same_fingerprint(actual: str, expected: str) -> None:
    if actual != expected:
        raise AppError(
            "IDEMPOTENCY_KEY_REUSED",
            "idempotency key was already used for a different request",
            409,
        )


def _require_status(task: HeroGenerationTaskRecord, expected: str) -> None:
    if task.status != expected:
        _invalid_state()


def _invalid_state() -> None:
    raise AppError(
        "HERO_GENERATION_INVALID_STATE",
        "hero generation task is not in the required state",
        409,
    )
