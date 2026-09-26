from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


@dataclass(frozen=True)
class SuitePlanModuleInput:
    module_key: str
    position: int
    requested_image_count: int
    title: str
    module_parameters: list[dict[str, str]] = field(default_factory=list)
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SuitePlanModuleCompilation:
    copy_summary: str
    visual_direction: str
    task_prompt: str
    compiler_output: dict[str, Any]


@dataclass
class SuitePlanRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    status: str
    revision: int
    requested_module_count: int
    compile_idempotency_key: str
    compile_fingerprint: str
    snapshot: dict[str, Any]
    confirm_idempotency_key: str | None = None
    confirm_fingerprint: str | None = None
    confirmed_snapshot: dict[str, Any] | None = None
    generation_batch_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: datetime | None = None


@dataclass
class SuitePlanModuleRecord:
    id: UUID
    plan_id: UUID
    module_key: str
    position: int
    requested_image_count: int
    revision: int
    title: str
    copy_summary: str
    visual_direction: str
    module_parameters: list[dict[str, str]]
    prompt_snapshot: dict[str, Any]
    compiled_task_prompt: str | None = None
    compiler_output: dict[str, Any] | None = None
    current_task_prompt: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class SuitePlanDetail:
    plan: SuitePlanRecord
    modules: list[SuitePlanModuleRecord]


class InMemorySuitePlanningRepository:
    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        state = backing_store if backing_store is not None else {}
        self._plans: dict[UUID, SuitePlanRecord] = state.setdefault("suite_plans", {})
        self._modules: dict[UUID, SuitePlanModuleRecord] = state.setdefault(
            "suite_plan_modules", {}
        )

    async def create_compiling(
        self,
        workspace_id: UUID,
        project_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
        module_inputs: list[SuitePlanModuleInput],
    ) -> tuple[SuitePlanRecord, bool]:
        _validate_module_inputs(module_inputs)
        existing = next(
            (
                plan
                for plan in self._plans.values()
                if plan.workspace_id == workspace_id
                and plan.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        if existing is not None:
            _same_fingerprint(existing.compile_fingerprint, fingerprint)
            return deepcopy(existing), True

        now = datetime.now(timezone.utc)
        plan = SuitePlanRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            status="compiling",
            revision=1,
            requested_module_count=len(module_inputs),
            compile_idempotency_key=idempotency_key,
            compile_fingerprint=fingerprint,
            snapshot=deepcopy(snapshot),
            created_at=now,
            updated_at=now,
        )
        self._plans[plan.id] = plan
        for item in module_inputs:
            module = SuitePlanModuleRecord(
                id=uuid4(),
                plan_id=plan.id,
                module_key=item.module_key,
                position=item.position,
                requested_image_count=item.requested_image_count,
                revision=1,
                title=item.title,
                copy_summary="",
                visual_direction="",
                module_parameters=deepcopy(item.module_parameters),
                prompt_snapshot=deepcopy(item.prompt_snapshot),
                created_at=now,
                updated_at=now,
            )
            self._modules[module.id] = module
        return deepcopy(plan), False

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> SuitePlanRecord | None:
        plan = next(
            (
                item
                for item in self._plans.values()
                if item.workspace_id == workspace_id
                and item.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        return deepcopy(plan) if plan is not None else None

    async def get_by_confirm_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> SuitePlanRecord | None:
        plan = next(
            (
                item
                for item in self._plans.values()
                if item.workspace_id == workspace_id
                and item.confirm_idempotency_key == idempotency_key
            ),
            None,
        )
        return deepcopy(plan) if plan is not None else None

    async def get_plan_detail(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> SuitePlanDetail | None:
        plan = self._plans.get(plan_id)
        if plan is None or plan.workspace_id != workspace_id:
            return None
        if project_id is not None and plan.project_id != project_id:
            return None
        return self._detail(plan)

    async def get_latest(
        self, project_id: UUID, workspace_id: UUID
    ) -> SuitePlanDetail | None:
        candidates = [
            plan
            for plan in self._plans.values()
            if plan.workspace_id == workspace_id and plan.project_id == project_id
        ]
        if not candidates:
            return None
        return self._detail(max(candidates, key=lambda item: (item.created_at, str(item.id))))

    async def save_planning_snapshot(self, plan_id: UUID, workspace_id: UUID, snapshot: dict, module_snapshots: dict) -> None:
        plan = self._required_plan(plan_id, workspace_id)
        _require_status(plan, "compiling")
        modules = self._modules_for_plan(plan_id)
        _require_exact_keys(module_snapshots, {item.module_key for item in modules})
        plan.snapshot = deepcopy(snapshot)
        for module in modules:
            module.prompt_snapshot = deepcopy(module_snapshots[module.module_key])

    async def mark_awaiting_confirmation(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        compilations: dict[str, SuitePlanModuleCompilation],
    ) -> SuitePlanRecord:
        plan = self._required_plan(plan_id, workspace_id)
        _require_status(plan, "compiling")
        modules = self._modules_for_plan(plan_id)
        _require_exact_keys(compilations, {item.module_key for item in modules})
        now = datetime.now(timezone.utc)
        for module in modules:
            compiled = compilations[module.module_key]
            if not compiled.task_prompt.strip():
                raise AppError("SUITE_PLAN_COMPILATION_INVALID", "规划模块提示词不能为空", 502)
            module.copy_summary = compiled.copy_summary.strip()
            module.visual_direction = compiled.visual_direction.strip()
            module.compiled_task_prompt = compiled.task_prompt.strip()
            module.current_task_prompt = compiled.task_prompt.strip()
            module.compiler_output = deepcopy(compiled.compiler_output)
            module.updated_at = now
        plan.status = "awaiting_confirmation"
        plan.revision += 1
        plan.updated_at = now
        return deepcopy(plan)

    async def mark_failed(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        code: str,
        message: str,
    ) -> SuitePlanRecord:
        plan = self._required_plan(plan_id, workspace_id)
        _require_status(plan, "compiling")
        plan.status = "failed"
        plan.error_code = code
        plan.error_message = message
        plan.revision += 1
        plan.updated_at = datetime.now(timezone.utc)
        return deepcopy(plan)

    async def update_module(
        self,
        plan_id: UUID,
        module_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        expected_module_revision: int,
        title: str | None = None,
        copy_summary: str | None = None,
        visual_direction: str | None = None,
        current_task_prompt: str | None = None,
        requested_image_count: int | None = None,
        module_parameters: list[dict[str, str]] | None = None,
    ) -> SuitePlanDetail:
        plan = self._required_plan(plan_id, workspace_id, project_id)
        _require_editable(plan)
        module = self._modules.get(module_id)
        if module is None or module.plan_id != plan_id:
            raise AppError("SUITE_PLAN_MODULE_NOT_FOUND", "详情页规划模块不存在", 404)
        if plan.revision != expected_plan_revision or module.revision != expected_module_revision:
            raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)
        if requested_image_count is not None and requested_image_count not in {1, 2, 3, 4}:
            raise AppError("SUITE_PLAN_INVALID_INPUT", "模块生成数量必须为 1 到 4", 400)
        normalized_title = title.strip() if title is not None else None
        normalized_prompt = current_task_prompt.strip() if current_task_prompt is not None else None
        if normalized_title == "" or normalized_prompt == "":
            raise AppError("SUITE_PLAN_INVALID_INPUT", "模块标题和实时任务提示词不能为空", 400)

        if normalized_title is not None:
            module.title = normalized_title
        if copy_summary is not None:
            module.copy_summary = copy_summary.strip()
        if visual_direction is not None:
            module.visual_direction = visual_direction.strip()
        if normalized_prompt is not None:
            module.current_task_prompt = normalized_prompt
        if requested_image_count is not None:
            module.requested_image_count = requested_image_count
        if module_parameters is not None:
            module.module_parameters = deepcopy(module_parameters)
        now = datetime.now(timezone.utc)
        module.revision += 1
        module.updated_at = now
        plan.revision += 1
        plan.updated_at = now
        return self._detail(plan)

    async def reorder_modules(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        ordered_module_ids: list[UUID],
    ) -> SuitePlanDetail:
        plan = self._required_plan(plan_id, workspace_id, project_id)
        _require_editable(plan)
        if plan.revision != expected_plan_revision:
            raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)
        modules = self._modules_for_plan(plan_id)
        if len(ordered_module_ids) != len(modules) or set(ordered_module_ids) != {
            item.id for item in modules
        }:
            raise AppError("SUITE_PLAN_INVALID_INPUT", "模块顺序必须包含全部规划模块", 400)
        by_id = {item.id: item for item in modules}
        now = datetime.now(timezone.utc)
        for position, module_id in enumerate(ordered_module_ids, start=1):
            module = by_id[module_id]
            if module.position != position:
                module.position = position
                module.revision += 1
                module.updated_at = now
        plan.revision += 1
        plan.updated_at = now
        return self._detail(plan)

    async def mark_confirmed(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        idempotency_key: str,
        fingerprint: str,
        confirmed_snapshot: dict[str, Any],
        generation_batch_id: UUID,
    ) -> tuple[SuitePlanRecord, bool]:
        plan = self._required_plan(plan_id, workspace_id, project_id)
        if plan.confirm_idempotency_key == idempotency_key:
            _same_fingerprint(plan.confirm_fingerprint or "", fingerprint)
            return deepcopy(plan), True
        conflict = next(
            (
                item
                for item in self._plans.values()
                if item.workspace_id == workspace_id
                and item.confirm_idempotency_key == idempotency_key
            ),
            None,
        )
        if conflict is not None:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
        _require_editable(plan)
        if plan.revision != expected_plan_revision:
            raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)
        now = datetime.now(timezone.utc)
        plan.status = "confirmed"
        plan.revision += 1
        plan.confirm_idempotency_key = idempotency_key
        plan.confirm_fingerprint = fingerprint
        plan.confirmed_snapshot = deepcopy(confirmed_snapshot)
        plan.generation_batch_id = generation_batch_id
        plan.confirmed_at = now
        plan.updated_at = now
        return deepcopy(plan), False

    def _required_plan(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> SuitePlanRecord:
        plan = self._plans.get(plan_id)
        if plan is None or plan.workspace_id != workspace_id:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        if project_id is not None and plan.project_id != project_id:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        return plan

    def _modules_for_plan(self, plan_id: UUID) -> list[SuitePlanModuleRecord]:
        return sorted(
            (item for item in self._modules.values() if item.plan_id == plan_id),
            key=lambda item: item.position,
        )

    def _detail(self, plan: SuitePlanRecord) -> SuitePlanDetail:
        return SuitePlanDetail(deepcopy(plan), deepcopy(self._modules_for_plan(plan.id)))

    async def ready(self) -> bool:
        return True


class PostgresSuitePlanningRepository:
    """使用行锁和修订条件保存详情页规划。"""

    async def save_planning_snapshot(self, plan_id: UUID, workspace_id: UUID, snapshot: dict, module_snapshots: dict) -> None:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id)
            _require_status(plan, "compiling")
            modules = await self._modules(session, plan_id, lock=True)
            _require_exact_keys(module_snapshots, {item.module_key for item in modules})
            await session.execute(text(
                "UPDATE project_workbench.suite_plans SET snapshot=CAST(:snapshot AS jsonb), updated_at=now() WHERE id=:id"
            ), {"id": plan_id, "snapshot": _dump_json(snapshot)})
            for module in modules:
                await session.execute(text(
                    "UPDATE project_workbench.suite_plan_modules SET prompt_snapshot=CAST(:snapshot AS jsonb), updated_at=now() WHERE id=:id"
                ), {"id": module.id, "snapshot": _dump_json(module_snapshots[module.module_key])})

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_compiling(
        self,
        workspace_id: UUID,
        project_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
        module_inputs: list[SuitePlanModuleInput],
    ) -> tuple[SuitePlanRecord, bool]:
        _validate_module_inputs(module_inputs)
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO project_workbench.suite_plans "
                    "(id, workspace_id, project_id, requested_module_count, "
                    "compile_idempotency_key, compile_fingerprint, snapshot) "
                    "VALUES (:id, :workspace_id, :project_id, :module_count, :key, "
                    ":fingerprint, CAST(:snapshot AS jsonb)) "
                    "ON CONFLICT (workspace_id, compile_idempotency_key) DO NOTHING "
                    f"RETURNING {_PLAN_COLUMNS}"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "module_count": len(module_inputs),
                    "key": idempotency_key,
                    "fingerprint": fingerprint,
                    "snapshot": _dump_json(snapshot),
                },
            )
            created = result.mappings().first()
            if created is None:
                existing = await session.execute(
                    text(
                        f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans "
                        "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                    ),
                    {"workspace_id": workspace_id, "key": idempotency_key},
                )
                plan = _plan_from_row(existing.mappings().one())
                _same_fingerprint(plan.compile_fingerprint, fingerprint)
                return plan, True
            plan = _plan_from_row(created)
            for item in module_inputs:
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.suite_plan_modules "
                        "(id, plan_id, module_key, position, requested_image_count, title, "
                        "module_parameters, prompt_snapshot) VALUES "
                        "(:id, :plan_id, :module_key, :position, :count, :title, "
                        "CAST(:parameters AS jsonb), CAST(:prompt_snapshot AS jsonb))"
                    ),
                    {
                        "id": uuid4(),
                        "plan_id": plan.id,
                        "module_key": item.module_key,
                        "position": item.position,
                        "count": item.requested_image_count,
                        "title": item.title,
                        "parameters": _dump_json(item.module_parameters),
                        "prompt_snapshot": _dump_json(item.prompt_snapshot),
                    },
                )
            return plan, False

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> SuitePlanRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                text(
                    f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans "
                    "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            row = result.mappings().first()
            return _plan_from_row(row) if row is not None else None

    async def get_by_confirm_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> SuitePlanRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                text(
                    f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans "
                    "WHERE workspace_id=:workspace_id AND confirm_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            row = result.mappings().first()
            return _plan_from_row(row) if row is not None else None

    async def get_plan_detail(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> SuitePlanDetail | None:
        async with self.sessions() as session:
            conditions = "id=:id AND workspace_id=:workspace_id"
            params: dict[str, Any] = {"id": plan_id, "workspace_id": workspace_id}
            if project_id is not None:
                conditions += " AND project_id=:project_id"
                params["project_id"] = project_id
            result = await session.execute(
                text(
                    f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans WHERE {conditions}"
                ),
                params,
            )
            row = result.mappings().first()
            if row is None:
                return None
            plan = _plan_from_row(row)
            return SuitePlanDetail(plan, await self._modules(session, plan.id))

    async def get_latest(
        self, project_id: UUID, workspace_id: UUID
    ) -> SuitePlanDetail | None:
        async with self.sessions() as session:
            result = await session.execute(
                text(
                    f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans "
                    "WHERE project_id=:project_id AND workspace_id=:workspace_id "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            plan = _plan_from_row(row)
            return SuitePlanDetail(plan, await self._modules(session, plan.id))

    async def mark_awaiting_confirmation(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        compilations: dict[str, SuitePlanModuleCompilation],
    ) -> SuitePlanRecord:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id)
            _require_status(plan, "compiling")
            modules = await self._modules(session, plan_id, lock=True)
            _require_exact_keys(compilations, {item.module_key for item in modules})
            for module in modules:
                compiled = compilations[module.module_key]
                if not compiled.task_prompt.strip():
                    raise AppError("SUITE_PLAN_COMPILATION_INVALID", "规划模块提示词不能为空", 502)
                await session.execute(
                    text(
                        "UPDATE project_workbench.suite_plan_modules SET "
                        "copy_summary=:copy_summary, visual_direction=:visual_direction, "
                        "compiled_task_prompt=:task_prompt, current_task_prompt=:task_prompt, "
                        "compiler_output=CAST(:compiler_output AS jsonb), updated_at=now() "
                        "WHERE id=:id"
                    ),
                    {
                        "id": module.id,
                        "copy_summary": compiled.copy_summary.strip(),
                        "visual_direction": compiled.visual_direction.strip(),
                        "task_prompt": compiled.task_prompt.strip(),
                        "compiler_output": _dump_json(compiled.compiler_output),
                    },
                )
            result = await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET "
                    "status='awaiting_confirmation', revision=revision+1, updated_at=now() "
                    f"WHERE id=:id RETURNING {_PLAN_COLUMNS}"
                ),
                {"id": plan_id},
            )
            return _plan_from_row(result.mappings().one())

    async def mark_failed(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        code: str,
        message: str,
    ) -> SuitePlanRecord:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id)
            _require_status(plan, "compiling")
            result = await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET status='failed', revision=revision+1, "
                    "error_code=:code, error_message=:message, updated_at=now() "
                    f"WHERE id=:id RETURNING {_PLAN_COLUMNS}"
                ),
                {"id": plan_id, "code": code, "message": message},
            )
            return _plan_from_row(result.mappings().one())

    async def update_module(
        self,
        plan_id: UUID,
        module_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        expected_module_revision: int,
        title: str | None = None,
        copy_summary: str | None = None,
        visual_direction: str | None = None,
        current_task_prompt: str | None = None,
        requested_image_count: int | None = None,
        module_parameters: list[dict[str, str]] | None = None,
    ) -> SuitePlanDetail:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id, project_id)
            _require_editable(plan)
            if plan.revision != expected_plan_revision:
                _revision_conflict()
            module_result = await session.execute(
                text(
                    f"SELECT {_MODULE_COLUMNS} FROM project_workbench.suite_plan_modules "
                    "WHERE id=:id AND plan_id=:plan_id FOR UPDATE"
                ),
                {"id": module_id, "plan_id": plan_id},
            )
            module_row = module_result.mappings().first()
            if module_row is None:
                raise AppError("SUITE_PLAN_MODULE_NOT_FOUND", "详情页规划模块不存在", 404)
            module = _module_from_row(module_row)
            if module.revision != expected_module_revision:
                _revision_conflict()
            if requested_image_count is not None and requested_image_count not in {1, 2, 3, 4}:
                raise AppError("SUITE_PLAN_INVALID_INPUT", "模块生成数量必须为 1 到 4", 400)
            resolved_title = module.title if title is None else title.strip()
            resolved_prompt = (
                module.current_task_prompt
                if current_task_prompt is None
                else current_task_prompt.strip()
            )
            if not resolved_title or not resolved_prompt:
                raise AppError("SUITE_PLAN_INVALID_INPUT", "模块标题和实时任务提示词不能为空", 400)
            await session.execute(
                text(
                    "UPDATE project_workbench.suite_plan_modules SET title=:title, "
                    "copy_summary=:copy_summary, visual_direction=:visual_direction, "
                    "current_task_prompt=:current_task_prompt, requested_image_count=:count, "
                    "module_parameters=CAST(:parameters AS jsonb), revision=revision+1, "
                    "updated_at=now() WHERE id=:id AND revision=:expected_revision"
                ),
                {
                    "id": module.id,
                    "expected_revision": expected_module_revision,
                    "title": resolved_title,
                    "copy_summary": module.copy_summary if copy_summary is None else copy_summary.strip(),
                    "visual_direction": (
                        module.visual_direction
                        if visual_direction is None
                        else visual_direction.strip()
                    ),
                    "current_task_prompt": resolved_prompt,
                    "count": (
                        module.requested_image_count
                        if requested_image_count is None
                        else requested_image_count
                    ),
                    "parameters": _dump_json(
                        module.module_parameters
                        if module_parameters is None
                        else module_parameters
                    ),
                },
            )
            plan_update = await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET revision=revision+1, updated_at=now() "
                    "WHERE id=:id AND revision=:expected_revision RETURNING revision"
                ),
                {"id": plan.id, "expected_revision": expected_plan_revision},
            )
            if plan_update.mappings().first() is None:
                _revision_conflict()
        detail = await self.get_plan_detail(plan_id, workspace_id, project_id)
        if detail is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        return detail

    async def reorder_modules(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        ordered_module_ids: list[UUID],
    ) -> SuitePlanDetail:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id, project_id)
            _require_editable(plan)
            if plan.revision != expected_plan_revision:
                _revision_conflict()
            modules = await self._modules(session, plan_id, lock=True)
            if len(ordered_module_ids) != len(modules) or set(ordered_module_ids) != {
                item.id for item in modules
            }:
                raise AppError("SUITE_PLAN_INVALID_INPUT", "模块顺序必须包含全部规划模块", 400)
            changed = {
                module_id: position
                for position, module_id in enumerate(ordered_module_ids, start=1)
                if next(item.position for item in modules if item.id == module_id) != position
            }
            if changed:
                cases = " ".join(
                    f"WHEN :module_{index} THEN :position_{index}"
                    for index in range(len(changed))
                )
                params: dict[str, Any] = {"plan_id": plan_id}
                ids: list[UUID] = []
                for index, (module_id, position) in enumerate(changed.items()):
                    params[f"module_{index}"] = module_id
                    params[f"position_{index}"] = position
                    ids.append(module_id)
                params["module_ids"] = ids
                await session.execute(
                    text(
                        "UPDATE project_workbench.suite_plan_modules "
                        "SET position=position+:offset WHERE plan_id=:plan_id AND id = ANY(:module_ids)"
                    ),
                    {"plan_id": plan_id, "module_ids": ids, "offset": max(item.position for item in modules) + 1},
                )
                await session.execute(
                    text(
                        "UPDATE project_workbench.suite_plan_modules SET position=CASE id "
                        f"{cases} ELSE position END, revision=revision+1, updated_at=now() "
                        "WHERE plan_id=:plan_id AND id = ANY(:module_ids)"
                    ),
                    params,
                )
            plan_update = await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET revision=revision+1, updated_at=now() "
                    "WHERE id=:id AND revision=:expected_revision RETURNING revision"
                ),
                {"id": plan.id, "expected_revision": expected_plan_revision},
            )
            if plan_update.mappings().first() is None:
                _revision_conflict()
        detail = await self.get_plan_detail(plan_id, workspace_id, project_id)
        if detail is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        return detail

    async def mark_confirmed(
        self,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        *,
        expected_plan_revision: int,
        idempotency_key: str,
        fingerprint: str,
        confirmed_snapshot: dict[str, Any],
        generation_batch_id: UUID,
    ) -> tuple[SuitePlanRecord, bool]:
        async with self.sessions() as session, session.begin():
            plan = await self._locked_plan(session, plan_id, workspace_id, project_id)
            if plan.confirm_idempotency_key == idempotency_key:
                _same_fingerprint(plan.confirm_fingerprint or "", fingerprint)
                return plan, True
            _require_editable(plan)
            if plan.revision != expected_plan_revision:
                _revision_conflict()
            conflicting = await session.scalar(
                text(
                    "SELECT id FROM project_workbench.suite_plans "
                    "WHERE workspace_id=:workspace_id AND confirm_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            if conflicting is not None:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            result = await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET status='confirmed', "
                    "revision=revision+1, confirm_idempotency_key=:key, "
                    "confirm_fingerprint=:fingerprint, "
                    "confirmed_snapshot=CAST(:snapshot AS jsonb), "
                    "generation_batch_id=:batch_id, confirmed_at=now(), updated_at=now() "
                    f"WHERE id=:id RETURNING {_PLAN_COLUMNS}"
                ),
                {
                    "id": plan.id,
                    "key": idempotency_key,
                    "fingerprint": fingerprint,
                    "snapshot": _dump_json(confirmed_snapshot),
                    "batch_id": generation_batch_id,
                },
            )
            return _plan_from_row(result.mappings().one()), False

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(
                    await session.scalar(
                        text("SELECT to_regclass('project_workbench.suite_plans') IS NOT NULL")
                    )
                )
        except Exception:
            return False

    async def _locked_plan(
        self,
        session: AsyncSession,
        plan_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> SuitePlanRecord:
        conditions = "id=:id AND workspace_id=:workspace_id"
        params: dict[str, Any] = {"id": plan_id, "workspace_id": workspace_id}
        if project_id is not None:
            conditions += " AND project_id=:project_id"
            params["project_id"] = project_id
        result = await session.execute(
            text(
                f"SELECT {_PLAN_COLUMNS} FROM project_workbench.suite_plans "
                f"WHERE {conditions} FOR UPDATE"
            ),
            params,
        )
        row = result.mappings().first()
        if row is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        return _plan_from_row(row)

    async def _modules(
        self, session: AsyncSession, plan_id: UUID, *, lock: bool = False
    ) -> list[SuitePlanModuleRecord]:
        suffix = " FOR UPDATE" if lock else ""
        result = await session.execute(
            text(
                f"SELECT {_MODULE_COLUMNS} FROM project_workbench.suite_plan_modules "
                "WHERE plan_id=:plan_id ORDER BY position" + suffix
            ),
            {"plan_id": plan_id},
        )
        return [_module_from_row(row) for row in result.mappings().all()]


_PLAN_COLUMNS = (
    "id, workspace_id, project_id, status, revision, requested_module_count, "
    "compile_idempotency_key, compile_fingerprint, confirm_idempotency_key, "
    "confirm_fingerprint, snapshot, confirmed_snapshot, generation_batch_id, "
    "error_code, error_message, created_at, updated_at, confirmed_at"
)
_MODULE_COLUMNS = (
    "id, plan_id, module_key, position, requested_image_count, revision, title, "
    "copy_summary, visual_direction, module_parameters, prompt_snapshot, "
    "compiled_task_prompt, compiler_output, current_task_prompt, created_at, updated_at"
)


def _plan_from_row(row: Any) -> SuitePlanRecord:
    return SuitePlanRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        status=row["status"],
        revision=row["revision"],
        requested_module_count=row["requested_module_count"],
        compile_idempotency_key=row["compile_idempotency_key"],
        compile_fingerprint=row["compile_fingerprint"],
        snapshot=_json_value(row["snapshot"]),
        confirm_idempotency_key=row["confirm_idempotency_key"],
        confirm_fingerprint=row["confirm_fingerprint"],
        confirmed_snapshot=_optional_json(row["confirmed_snapshot"]),
        generation_batch_id=row["generation_batch_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        confirmed_at=row["confirmed_at"],
    )


def _module_from_row(row: Any) -> SuitePlanModuleRecord:
    return SuitePlanModuleRecord(
        id=row["id"],
        plan_id=row["plan_id"],
        module_key=row["module_key"],
        position=row["position"],
        requested_image_count=row["requested_image_count"],
        revision=row["revision"],
        title=row["title"],
        copy_summary=row["copy_summary"],
        visual_direction=row["visual_direction"],
        module_parameters=_json_value(row["module_parameters"]),
        prompt_snapshot=_json_value(row["prompt_snapshot"]),
        compiled_task_prompt=row["compiled_task_prompt"],
        compiler_output=_optional_json(row["compiler_output"]),
        current_task_prompt=row["current_task_prompt"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else deepcopy(value)


def _optional_json(value: Any) -> Any:
    return None if value is None else _json_value(value)


def _revision_conflict() -> None:
    raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)


def _validate_module_inputs(module_inputs: list[SuitePlanModuleInput]) -> None:
    if not module_inputs:
        raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页规划必须至少包含一个模块", 400)
    keys = [item.module_key.strip() for item in module_inputs]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页规划模块不能重复或为空", 400)
    if sorted(item.position for item in module_inputs) != list(range(1, len(module_inputs) + 1)):
        raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页规划模块顺序必须连续", 400)
    if any(item.requested_image_count not in {1, 2, 3, 4} for item in module_inputs):
        raise AppError("SUITE_PLAN_INVALID_INPUT", "模块生成数量必须为 1 到 4", 400)
    if any(not item.title.strip() for item in module_inputs):
        raise AppError("SUITE_PLAN_INVALID_INPUT", "模块标题不能为空", 400)


def _require_exact_keys(values: dict[str, Any], expected: set[str]) -> None:
    if set(values) != expected:
        raise AppError("SUITE_PLAN_COMPILATION_INVALID", "规划编译结果与模块不一致", 502)


def _require_status(plan: SuitePlanRecord, status: str) -> None:
    if plan.status != status:
        raise AppError("SUITE_PLAN_STATE_INVALID", "详情页规划状态不允许此操作", 409)


def _require_editable(plan: SuitePlanRecord) -> None:
    if plan.status != "awaiting_confirmation":
        raise AppError("SUITE_PLAN_NOT_EDITABLE", "只有待确认规划可以编辑", 409)


def _same_fingerprint(actual: str, expected: str) -> None:
    if actual != expected:
        raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
