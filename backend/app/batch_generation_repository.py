from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


@dataclass(frozen=True)
class GenerationModuleInput:
    module_key: str
    requested_image_count: int
    snapshot: dict[str, Any]
    position: int | None = None


@dataclass(frozen=True)
class ConfirmedGenerationModuleInput:
    module_key: str
    position: int
    requested_image_count: int
    snapshot: dict[str, Any]
    compiled_task_prompt: str
    compiler_output: dict[str, Any]
    confirmed_task_prompt: str
    final_prompt: str
    final_prompt_sha256: str


@dataclass(frozen=True)
class GenerationModuleCompilation:
    task_prompt: str
    compiler_output: dict[str, Any]


@dataclass(frozen=True)
class GenerationModuleConfirmation:
    task_prompt: str
    final_prompt: str
    final_prompt_sha256: str


@dataclass
class GenerationBatchRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    source_asset_id: UUID
    status: str
    compile_idempotency_key: str
    compile_fingerprint: str
    snapshot: dict[str, Any]
    kind: str = "hero"
    source_plan_id: UUID | None = None
    confirm_idempotency_key: str | None = None
    confirm_fingerprint: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class GenerationModuleTaskRecord:
    id: UUID
    batch_id: UUID
    module_key: str
    requested_image_count: int
    snapshot: dict[str, Any]
    position: int = 1
    compiled_task_prompt: str | None = None
    compiler_output: dict[str, Any] | None = None
    confirmed_task_prompt: str | None = None
    final_prompt: str | None = None
    final_prompt_sha256: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: datetime | None = None


@dataclass
class GenerationImageSlotRecord:
    id: UUID
    batch_id: UUID
    module_task_id: UUID
    module_key: str
    ordinal: int
    status: str
    generated_asset_id: UUID | None = None
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None
    provider_idempotency_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class GenerationSlotAttemptRecord:
    id: UUID
    slot_id: UUID
    attempt_no: int
    status: str
    lease_token: UUID
    worker_id: str | None = None
    provider_request_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class GenerationBatchProgress:
    total: int
    queued: int
    leased: int
    dispatching: int
    succeeded: int
    failed: int
    cancelled: int
    needs_retry: int

    @property
    def completed(self) -> int:
        return self.succeeded + self.failed + self.cancelled + self.needs_retry


@dataclass(frozen=True)
class GenerationBatchDetail:
    batch: GenerationBatchRecord
    module_tasks: list[GenerationModuleTaskRecord]
    slots: list[GenerationImageSlotRecord]
    progress: GenerationBatchProgress


@dataclass(frozen=True)
class GenerationSlotExecution:
    batch: GenerationBatchRecord
    module_task: GenerationModuleTaskRecord
    slot: GenerationImageSlotRecord


class InMemoryBatchGenerationRepository:
    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        state = backing_store if backing_store is not None else {}
        self._batches: dict[UUID, GenerationBatchRecord] = state.setdefault("generation_batches", {})
        self._module_tasks: dict[UUID, GenerationModuleTaskRecord] = state.setdefault(
            "generation_module_tasks", {}
        )
        self._slots: dict[UUID, GenerationImageSlotRecord] = state.setdefault(
            "generation_image_slots", {}
        )
        self._attempts: dict[UUID, GenerationSlotAttemptRecord] = state.setdefault(
            "generation_slot_attempts", {}
        )

    async def create_compiling(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_asset_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
        module_inputs: list[GenerationModuleInput],
    ) -> tuple[GenerationBatchRecord, bool]:
        _validate_module_inputs(module_inputs)
        existing = next(
            (
                batch
                for batch in self._batches.values()
                if batch.workspace_id == workspace_id
                and batch.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        if existing is not None:
            _same_fingerprint(existing.compile_fingerprint, fingerprint)
            return _copy(existing), True
        now = datetime.now(timezone.utc)
        batch = GenerationBatchRecord(
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
        self._batches[batch.id] = batch
        for position, module_input in enumerate(module_inputs, start=1):
            task = GenerationModuleTaskRecord(
                uuid4(),
                batch.id,
                module_input.module_key,
                module_input.requested_image_count,
                deepcopy(module_input.snapshot),
                position=module_input.position or position,
                created_at=now,
                updated_at=now,
            )
            self._module_tasks[task.id] = task
        return _copy(batch), False

    async def create_confirmed_from_plan(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_plan_id: UUID,
        source_asset_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        snapshot: dict[str, Any],
        module_inputs: list[ConfirmedGenerationModuleInput],
    ) -> tuple[GenerationBatchRecord, bool]:
        _validate_confirmed_module_inputs(module_inputs)
        existing = next(
            (
                batch for batch in self._batches.values()
                if batch.workspace_id == workspace_id and batch.source_plan_id == source_plan_id
            ),
            None,
        )
        if existing is not None:
            _same_fingerprint(existing.confirm_fingerprint or "", fingerprint)
            return _copy(existing), True
        key_conflict = next(
            (
                batch for batch in self._batches.values()
                if batch.workspace_id == workspace_id
                and batch.confirm_idempotency_key == idempotency_key
            ),
            None,
        )
        if key_conflict is not None:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)

        now = datetime.now(timezone.utc)
        batch = GenerationBatchRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            source_asset_id=source_asset_id,
            status="queued",
            compile_idempotency_key=f"suite-plan:{source_plan_id}",
            compile_fingerprint=fingerprint,
            snapshot=deepcopy(snapshot),
            kind="suite",
            source_plan_id=source_plan_id,
            confirm_idempotency_key=idempotency_key,
            confirm_fingerprint=fingerprint,
            created_at=now,
            updated_at=now,
            confirmed_at=now,
        )
        self._batches[batch.id] = batch
        for item in sorted(module_inputs, key=lambda value: value.position):
            task = GenerationModuleTaskRecord(
                id=uuid4(),
                batch_id=batch.id,
                module_key=item.module_key,
                requested_image_count=item.requested_image_count,
                snapshot=deepcopy(item.snapshot),
                position=item.position,
                compiled_task_prompt=item.compiled_task_prompt,
                compiler_output=deepcopy(item.compiler_output),
                confirmed_task_prompt=item.confirmed_task_prompt,
                final_prompt=item.final_prompt,
                final_prompt_sha256=item.final_prompt_sha256,
                created_at=now,
                updated_at=now,
                confirmed_at=now,
            )
            self._module_tasks[task.id] = task
            for ordinal in range(1, item.requested_image_count + 1):
                slot = GenerationImageSlotRecord(
                    uuid4(), batch.id, task.id, task.module_key, ordinal, "queued",
                    created_at=now, updated_at=now,
                )
                self._slots[slot.id] = slot
        return _copy(batch), False

    async def discard_suite_batch(
        self, batch_id: UUID, workspace_id: UUID, source_plan_id: UUID
    ) -> None:
        batch = self._batches.get(batch_id)
        if (
            batch is None
            or batch.workspace_id != workspace_id
            or batch.kind != "suite"
            or batch.source_plan_id != source_plan_id
        ):
            return
        task_ids = {
            task.id for task in self._module_tasks.values() if task.batch_id == batch_id
        }
        slot_ids = {slot.id for slot in self._slots.values() if slot.batch_id == batch_id}
        for attempt_id in [
            key for key, value in self._attempts.items() if value.slot_id in slot_ids
        ]:
            del self._attempts[attempt_id]
        for slot_id in slot_ids:
            del self._slots[slot_id]
        for task_id in task_ids:
            del self._module_tasks[task_id]
        del self._batches[batch_id]

    async def get_batch(
        self, batch_id: UUID, workspace_id: UUID
    ) -> GenerationBatchRecord | None:
        batch = self._batches.get(batch_id)
        return _copy(batch) if batch is not None and batch.workspace_id == workspace_id else None

    async def get_latest(self, project_id: UUID, workspace_id: UUID, *, kind: str | None = None) -> GenerationBatchRecord | None:
        candidates = [
            batch for batch in self._batches.values()
            if batch.project_id == project_id and batch.workspace_id == workspace_id
            and (kind is None or batch.kind == kind)
        ]
        return _copy(max(candidates, key=lambda item: (item.updated_at, str(item.id)))) if candidates else None

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> GenerationBatchRecord | None:
        batch = next(
            (
                item
                for item in self._batches.values()
                if item.workspace_id == workspace_id
                and item.compile_idempotency_key == idempotency_key
            ),
            None,
        )
        return _copy(batch) if batch is not None else None

    async def save_planning_snapshot(self, batch_id: UUID, workspace_id: UUID, snapshot: dict, module_snapshots: dict) -> None:
        batch = self._required_batch(batch_id, workspace_id)
        _require_status(batch.status, "compiling_prompt")
        tasks = self._tasks_for_batch(batch_id)
        _require_exact_keys(module_snapshots, {task.module_key for task in tasks})
        batch.snapshot = deepcopy(snapshot)
        for task in tasks:
            task.snapshot = deepcopy(module_snapshots[task.module_key])

    async def mark_failed(self, batch_id: UUID, workspace_id: UUID, code: str, message: str):
        batch = self._required_batch(batch_id, workspace_id)
        _require_status(batch.status, "compiling_prompt")
        batch.status = "failed"
        batch.error_code, batch.error_message = code, message
        batch.updated_at = datetime.now(timezone.utc)
        return _copy(batch)

    async def mark_awaiting_confirmation(
        self,
        batch_id: UUID,
        workspace_id: UUID,
        compilations: dict[str, GenerationModuleCompilation],
    ) -> GenerationBatchRecord:
        batch = self._required_batch(batch_id, workspace_id)
        _require_status(batch.status, "compiling_prompt")
        tasks = self._tasks_for_batch(batch_id)
        _require_exact_keys(compilations, {task.module_key for task in tasks})
        now = datetime.now(timezone.utc)
        for task in tasks:
            compilation = compilations[task.module_key]
            task.compiled_task_prompt = compilation.task_prompt
            task.compiler_output = deepcopy(compilation.compiler_output)
            task.updated_at = now
        batch.status = "awaiting_confirmation"
        batch.updated_at = now
        return _copy(batch)

    async def confirm_and_enqueue(
        self,
        batch_id: UUID,
        workspace_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        confirmations: dict[str, GenerationModuleConfirmation],
    ) -> tuple[GenerationBatchRecord, bool]:
        batch = self._required_batch(batch_id, workspace_id)
        if batch.confirm_idempotency_key == idempotency_key:
            _same_fingerprint(batch.confirm_fingerprint or "", fingerprint)
            return _copy(batch), True
        conflict = next(
            (
                item
                for item in self._batches.values()
                if item.workspace_id == workspace_id
                and item.confirm_idempotency_key == idempotency_key
            ),
            None,
        )
        if conflict is not None:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "idempotency key was already used for a different request", 409)
        _require_status(batch.status, "awaiting_confirmation")
        tasks = self._tasks_for_batch(batch_id)
        _require_exact_keys(confirmations, {task.module_key for task in tasks})
        now = datetime.now(timezone.utc)
        batch.status = "queued"
        batch.confirm_idempotency_key = idempotency_key
        batch.confirm_fingerprint = fingerprint
        batch.confirmed_at = now
        batch.updated_at = now
        for task in tasks:
            confirmation = confirmations[task.module_key]
            task.confirmed_task_prompt = confirmation.task_prompt
            task.final_prompt = confirmation.final_prompt
            task.final_prompt_sha256 = confirmation.final_prompt_sha256
            task.confirmed_at = now
            task.updated_at = now
            for ordinal in range(1, task.requested_image_count + 1):
                slot = GenerationImageSlotRecord(
                    uuid4(), batch.id, task.id, task.module_key, ordinal, "queued", created_at=now, updated_at=now
                )
                self._slots[slot.id] = slot
        return _copy(batch), False

    async def get_batch_detail(
        self, batch_id: UUID, workspace_id: UUID
    ) -> GenerationBatchDetail | None:
        batch = await self.get_batch(batch_id, workspace_id)
        if batch is None:
            return None
        tasks = sorted(self._tasks_for_batch(batch_id), key=lambda task: task.position)
        slots = sorted(
            (slot for slot in self._slots.values() if slot.batch_id == batch_id),
            key=lambda slot: (
                self._module_tasks[slot.module_task_id].position,
                slot.ordinal,
            ),
        )
        return GenerationBatchDetail(_copy(batch), _copy(tasks), _copy(slots), _progress(slots))

    async def claim_queued_slots(
        self,
        worker_id: str,
        *,
        limit: int,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> list[GenerationImageSlotRecord]:
        if limit < 1:
            return []
        claimed_at = now or datetime.now(timezone.utc)
        slots = sorted(
            (
                slot
                for slot in self._slots.values()
                if slot.status == "queued"
            ),
            key=lambda slot: (
                self._batches[slot.batch_id].created_at,
                self._module_tasks[slot.module_task_id].position,
                slot.ordinal,
                str(slot.id),
            ),
        )[:limit]
        for slot in slots:
            lease_token = uuid4()
            slot.status = "leased"
            slot.lease_token = lease_token
            slot.lease_expires_at = claimed_at + lease_duration
            slot.updated_at = claimed_at
            attempt_no = 1 + sum(1 for item in self._attempts.values() if item.slot_id == slot.id)
            attempt = GenerationSlotAttemptRecord(
                uuid4(), slot.id, attempt_no, "leased", lease_token, worker_id=worker_id,
                created_at=claimed_at, updated_at=claimed_at,
            )
            self._attempts[attempt.id] = attempt
            self._refresh_batch_status(slot.batch_id, claimed_at)
        return _copy(slots)

    async def renew_slot_lease(
        self, slot_id: UUID, lease_token: UUID, *, lease_duration: timedelta,
        now: datetime | None = None,
    ) -> bool:
        renewed_at = now or datetime.now(timezone.utc)
        slot = self._slots.get(slot_id)
        if (slot is None or slot.lease_token != lease_token
                or slot.status not in {"leased", "dispatching", "cancel_requested"}
                or slot.lease_expires_at is None or slot.lease_expires_at <= renewed_at):
            return False
        slot.lease_expires_at = renewed_at + lease_duration
        return True

    async def get_slot_execution(self, slot_id: UUID) -> GenerationSlotExecution | None:
        slot = self._slots.get(slot_id)
        if slot is None:
            return None
        batch = self._batches.get(slot.batch_id)
        task = self._module_tasks.get(slot.module_task_id)
        if batch is None or task is None:
            return None
        return GenerationSlotExecution(_copy(batch), _copy(task), _copy(slot))

    async def mark_dispatching(
        self,
        slot_id: UUID,
        lease_token: UUID | None,
        now: datetime | None = None,
        *,
        provider_request_summary: dict[str, Any] | None = None,
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        if slot.status != "leased" or slot.lease_token != lease_token:
            _invalid_state()
        dispatched_at = now or datetime.now(timezone.utc)
        slot.status = "dispatching"
        slot.dispatched_at = dispatched_at
        slot.updated_at = dispatched_at
        attempt = self._latest_attempt(slot.id)
        attempt.status = "dispatching"
        attempt.dispatched_at = dispatched_at
        attempt.updated_at = dispatched_at
        attempt.provider_request_summary = deepcopy(provider_request_summary)
        self._refresh_batch_status(slot.batch_id, dispatched_at)
        return _copy(slot)

    async def complete_slot(
        self, slot_id: UUID, lease_token: UUID | None, generated_asset_id: UUID,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        if slot.status != "dispatching" or slot.lease_token != lease_token:
            _invalid_state()
        completed_at = now or datetime.now(timezone.utc)
        slot.status = "succeeded"
        slot.generated_asset_id = generated_asset_id
        slot.completed_at = completed_at
        slot.updated_at = completed_at
        slot.lease_token = None
        slot.lease_expires_at = None
        attempt = self._latest_attempt(slot_id)
        attempt.status = "succeeded"
        attempt.completed_at = completed_at
        attempt.updated_at = completed_at
        self._refresh_batch_status(slot.batch_id, completed_at)
        return _copy(slot)

    async def fail_slot(
        self, slot_id: UUID, lease_token: UUID | None, code: str, message: str,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        if slot.status != "dispatching" or slot.lease_token != lease_token:
            _invalid_state()
        completed_at = now or datetime.now(timezone.utc)
        slot.status = "failed"
        slot.error_code = code
        slot.error_message = message
        slot.completed_at = completed_at
        slot.updated_at = completed_at
        slot.lease_token = None
        slot.lease_expires_at = None
        attempt = self._latest_attempt(slot_id)
        attempt.status = "failed"
        attempt.error_code = code
        attempt.error_message = message
        attempt.completed_at = completed_at
        attempt.updated_at = completed_at
        self._refresh_batch_status(slot.batch_id, completed_at)
        return _copy(slot)

    async def mark_needs_retry(
        self, slot_id: UUID, lease_token: UUID | None, code: str, message: str,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        if slot.status != "dispatching" or slot.lease_token != lease_token:
            _invalid_state()
        marked_at = now or datetime.now(timezone.utc)
        slot.status = "needs_retry"
        slot.error_code, slot.error_message = code, message
        slot.completed_at = marked_at
        slot.updated_at = marked_at
        slot.lease_token = None
        slot.lease_expires_at = None
        attempt = self._latest_attempt(slot_id)
        attempt.status = "needs_retry"
        attempt.error_code, attempt.error_message = code, message
        attempt.completed_at = marked_at
        attempt.updated_at = marked_at
        self._refresh_batch_status(slot.batch_id, marked_at)
        return _copy(slot)

    async def cancel_batch(
        self, batch_id: UUID, workspace_id: UUID, now: datetime | None = None
    ) -> GenerationBatchRecord:
        batch = self._required_batch(batch_id, workspace_id)
        cancelled_at = now or datetime.now(timezone.utc)
        has_dispatching = False
        for slot in self._slots.values():
            if slot.batch_id != batch_id:
                continue
            if slot.status in {"queued", "leased"}:
                slot.status = "cancelled"
                slot.lease_token = None
                slot.lease_expires_at = None
                slot.completed_at = cancelled_at
                slot.updated_at = cancelled_at
                attempts = [attempt for attempt in self._attempts.values() if attempt.slot_id == slot.id]
                if attempts:
                    attempt = max(attempts, key=lambda item: item.attempt_no)
                    attempt.status = "cancelled"
                    attempt.completed_at = cancelled_at
                    attempt.updated_at = cancelled_at
            elif slot.status in {"dispatching", "cancel_requested"}:
                slot.status = "cancel_requested"
                slot.updated_at = cancelled_at
                has_dispatching = True
        batch.status = "cancel_requested" if has_dispatching else "cancelled"
        batch.updated_at = cancelled_at
        if not has_dispatching:
            batch.completed_at = cancelled_at
        return _copy(batch)

    async def retry_slot(
        self, slot_id: UUID, workspace_id: UUID, now: datetime | None = None
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        batch = self._batches[slot.batch_id]
        if batch.workspace_id != workspace_id:
            raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
        if slot.status not in {"failed", "cancelled", "needs_retry"}:
            _invalid_state()
        retried_at = now or datetime.now(timezone.utc)
        slot.status = "queued"
        slot.lease_token = None
        slot.lease_expires_at = None
        slot.error_code = None
        slot.error_message = None
        slot.completed_at = None
        slot.updated_at = retried_at
        self._refresh_batch_status(slot.batch_id, retried_at)
        return _copy(slot)

    async def is_slot_cancel_requested(self, slot_id: UUID, lease_token: UUID | None) -> bool:
        slot = self._slots.get(slot_id)
        return bool(
            slot is not None
            and slot.status == "cancel_requested"
            and slot.lease_token == lease_token
        )

    async def complete_cancelled_slot(
        self, slot_id: UUID, lease_token: UUID | None, now: datetime | None = None
    ) -> GenerationImageSlotRecord:
        slot = self._required_slot(slot_id)
        if slot.status != "cancel_requested" or slot.lease_token != lease_token:
            _invalid_state()
        completed_at = now or datetime.now(timezone.utc)
        slot.status = "cancelled"
        slot.lease_token = None
        slot.lease_expires_at = None
        slot.completed_at = completed_at
        slot.updated_at = completed_at
        attempt = self._latest_attempt(slot_id)
        attempt.status = "cancelled"
        attempt.completed_at = completed_at
        attempt.updated_at = completed_at
        self._refresh_batch_status(slot.batch_id, completed_at)
        return _copy(slot)

    async def recover_expired_leases(self, now: datetime | None = None) -> int:
        recovered_at = now or datetime.now(timezone.utc)
        recovered = 0
        for slot in self._slots.values():
            if slot.status not in {"leased", "dispatching"} or slot.lease_expires_at is None:
                continue
            if slot.lease_expires_at > recovered_at:
                continue
            attempt = self._latest_attempt(slot.id)
            if slot.status == "leased":
                slot.status = "queued"
            else:
                slot.status = "needs_retry"
                slot.error_code = "PROVIDER_DISPATCH_UNKNOWN"
                slot.error_message = "生图请求结果不确定，需要人工重试"
                attempt.status = "needs_retry"
                attempt.error_code = slot.error_code
                attempt.error_message = slot.error_message
                attempt.completed_at = recovered_at
            slot.lease_token = None
            slot.lease_expires_at = None
            slot.updated_at = recovered_at
            attempt.updated_at = recovered_at
            self._refresh_batch_status(slot.batch_id, recovered_at)
            recovered += 1
        return recovered

    async def list_attempts(
        self, slot_id: UUID, workspace_id: UUID
    ) -> list[GenerationSlotAttemptRecord]:
        slot = self._slots.get(slot_id)
        batch = self._batches.get(slot.batch_id) if slot is not None else None
        if slot is None or batch is None or batch.workspace_id != workspace_id:
            return []
        attempts = sorted(
            (attempt for attempt in self._attempts.values() if attempt.slot_id == slot_id),
            key=lambda attempt: attempt.attempt_no,
        )
        return _copy(attempts)

    async def ready(self) -> bool:
        return True

    def _required_batch(self, batch_id: UUID, workspace_id: UUID) -> GenerationBatchRecord:
        batch = self._batches.get(batch_id)
        if batch is None or batch.workspace_id != workspace_id:
            raise AppError("BATCH_GENERATION_NOT_FOUND", "批次生成任务不存在", 404)
        return batch

    def _required_slot(self, slot_id: UUID) -> GenerationImageSlotRecord:
        slot = self._slots.get(slot_id)
        if slot is None:
            raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
        return slot

    def _tasks_for_batch(self, batch_id: UUID) -> list[GenerationModuleTaskRecord]:
        return [task for task in self._module_tasks.values() if task.batch_id == batch_id]

    def _latest_attempt(self, slot_id: UUID) -> GenerationSlotAttemptRecord:
        attempts = [attempt for attempt in self._attempts.values() if attempt.slot_id == slot_id]
        if not attempts:
            _invalid_state()
        return max(attempts, key=lambda attempt: attempt.attempt_no)

    def _refresh_batch_status(self, batch_id: UUID, now: datetime) -> None:
        batch = self._batches[batch_id]
        if batch.status in {"compiling_prompt", "awaiting_confirmation", "cancelled"}:
            return
        slots = [slot for slot in self._slots.values() if slot.batch_id == batch_id]
        progress = _progress(slots)
        if progress.dispatching:
            batch.status = "running"
        elif progress.queued or progress.leased:
            batch.status = "queued"
        elif progress.needs_retry or progress.failed:
            batch.status = "partially_failed" if progress.succeeded else "failed"
            batch.completed_at = now
        elif progress.cancelled:
            batch.status = "cancelled"
            batch.completed_at = now
        elif progress.total and progress.succeeded == progress.total:
            batch.status = "succeeded"
            batch.completed_at = now
        batch.updated_at = now


class PostgresBatchGenerationRepository:
    """PostgreSQL queue repository. Worker-facing mutations hold row locks in one transaction."""

    async def save_planning_snapshot(self, batch_id: UUID, workspace_id: UUID, snapshot: dict, module_snapshots: dict) -> None:
        async with self.sessions() as session, session.begin():
            batch = await self._locked_batch(session, batch_id, workspace_id)
            _require_status(batch.status, "compiling_prompt")
            tasks = await self._tasks(session, batch_id)
            _require_exact_keys(module_snapshots, {task.module_key for task in tasks})
            await session.execute(text(
                "UPDATE project_workbench.generation_batches SET snapshot=CAST(:snapshot AS jsonb), updated_at=now() WHERE id=:id"
            ), {"id": batch_id, "snapshot": _dump(snapshot)})
            for task in tasks:
                await session.execute(text(
                    "UPDATE project_workbench.generation_module_tasks SET snapshot=CAST(:snapshot AS jsonb), updated_at=now() WHERE id=:id"
                ), {"id": task.id, "snapshot": _dump(module_snapshots[task.module_key])})

    async def mark_failed(self, batch_id: UUID, workspace_id: UUID, code: str, message: str):
        async with self.sessions() as session, session.begin():
            batch = await self._locked_batch(session, batch_id, workspace_id)
            _require_status(batch.status, "compiling_prompt")
            result = await session.execute(text(
                "UPDATE project_workbench.generation_batches SET status='failed', error_code=:code, "
                f"error_message=:message, updated_at=now() WHERE id=:id RETURNING {_BATCH_COLUMNS}"
            ), {"id": batch_id, "code": code, "message": message})
            return _batch_from_row(result.mappings().one())

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
        module_inputs: list[GenerationModuleInput],
    ) -> tuple[GenerationBatchRecord, bool]:
        _validate_module_inputs(module_inputs)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.generation_batches "
                    "(id, workspace_id, project_id, source_asset_id, compile_idempotency_key, "
                    "compile_fingerprint, snapshot) VALUES (:id, :workspace_id, :project_id, "
                    ":source_asset_id, :key, :fingerprint, CAST(:snapshot AS jsonb)) "
                    "ON CONFLICT (workspace_id, compile_idempotency_key) DO NOTHING "
                    f"RETURNING {_BATCH_COLUMNS}"
                ),
                {
                    "id": uuid4(), "workspace_id": workspace_id, "project_id": project_id,
                    "source_asset_id": source_asset_id, "key": idempotency_key,
                    "fingerprint": fingerprint, "snapshot": _dump(snapshot),
                },
            )
            created = row.mappings().first()
            if created is None:
                existing = await session.execute(
                    text(
                        f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                        "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                    ),
                    {"workspace_id": workspace_id, "key": idempotency_key},
                )
                batch = _batch_from_row(existing.mappings().one())
                _same_fingerprint(batch.compile_fingerprint, fingerprint)
                return batch, True
            batch = _batch_from_row(created)
            for position, module_input in enumerate(module_inputs, start=1):
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_module_tasks "
                        "(id, batch_id, module_key, position, requested_image_count, snapshot) "
                        "VALUES (:id, :batch_id, :module_key, :position, :count, CAST(:snapshot AS jsonb))"
                    ),
                    {
                        "id": uuid4(), "batch_id": batch.id, "module_key": module_input.module_key,
                        "position": module_input.position or position,
                        "count": module_input.requested_image_count, "snapshot": _dump(module_input.snapshot),
                    },
                )
            return batch, False

    async def confirm_plan_and_create_batch(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        expected_plan_revision: int,
        source_asset_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        confirmed_snapshot: dict[str, Any],
        module_inputs: list[ConfirmedGenerationModuleInput],
    ) -> GenerationBatchRecord:
        """在一个 PostgreSQL 事务内冻结规划并建立全部套图槽位。"""
        _validate_confirmed_module_inputs(module_inputs)
        async with self.sessions() as session, session.begin():
            plan_result = await session.execute(
                text(
                    "SELECT status, revision, confirm_idempotency_key, confirm_fingerprint, "
                    "generation_batch_id FROM project_workbench.suite_plans "
                    "WHERE id=:plan_id AND workspace_id=:workspace_id AND project_id=:project_id "
                    "FOR UPDATE"
                ),
                {
                    "plan_id": plan_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )
            plan = plan_result.mappings().first()
            if plan is None:
                raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
            if plan["confirm_idempotency_key"] == idempotency_key:
                _same_fingerprint(plan["confirm_fingerprint"] or "", fingerprint)
                replay_result = await session.execute(
                    text(
                        f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                        "WHERE id=:batch_id AND workspace_id=:workspace_id"
                    ),
                    {
                        "batch_id": plan["generation_batch_id"],
                        "workspace_id": workspace_id,
                    },
                )
                replay = replay_result.mappings().first()
                if replay is None:
                    raise AppError(
                        "SUITE_PLAN_CONFIRMATION_INCOMPLETE", "规划确认记录不完整", 500
                    )
                return _batch_from_row(replay)
            if plan["status"] != "awaiting_confirmation":
                raise AppError("SUITE_PLAN_NOT_EDITABLE", "详情页规划当前状态不允许确认", 409)
            if plan["revision"] != expected_plan_revision:
                raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)
            conflicting = await session.scalar(
                text(
                    "SELECT id FROM project_workbench.generation_batches "
                    "WHERE workspace_id=:workspace_id AND confirm_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            if conflicting is not None:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)

            batch_id = uuid4()
            batch_result = await session.execute(
                text(
                    "INSERT INTO project_workbench.generation_batches "
                    "(id, workspace_id, project_id, source_asset_id, kind, source_plan_id, "
                    "status, compile_idempotency_key, compile_fingerprint, "
                    "confirm_idempotency_key, confirm_fingerprint, snapshot, confirmed_at) "
                    "VALUES (:id, :workspace_id, :project_id, :source_asset_id, 'suite', "
                    ":source_plan_id, 'queued', :compile_key, :fingerprint, :confirm_key, "
                    ":fingerprint, CAST(:snapshot AS jsonb), now()) "
                    f"RETURNING {_BATCH_COLUMNS}"
                ),
                {
                    "id": batch_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "source_asset_id": source_asset_id,
                    "source_plan_id": plan_id,
                    "compile_key": f"suite-plan:{plan_id}",
                    "confirm_key": idempotency_key,
                    "fingerprint": fingerprint,
                    "snapshot": _dump(confirmed_snapshot),
                },
            )
            batch = _batch_from_row(batch_result.mappings().one())
            for item in module_inputs:
                task_id = uuid4()
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_module_tasks "
                        "(id, batch_id, module_key, position, requested_image_count, snapshot, "
                        "compiled_task_prompt, compiler_output, confirmed_task_prompt, final_prompt, "
                        "final_prompt_sha256, confirmed_at) VALUES "
                        "(:id, :batch_id, :module_key, :position, :count, CAST(:snapshot AS jsonb), "
                        ":compiled_prompt, CAST(:compiler_output AS jsonb), :confirmed_prompt, "
                        ":final_prompt, :final_hash, now())"
                    ),
                    {
                        "id": task_id,
                        "batch_id": batch_id,
                        "module_key": item.module_key,
                        "position": item.position,
                        "count": item.requested_image_count,
                        "snapshot": _dump(item.snapshot),
                        "compiled_prompt": item.compiled_task_prompt,
                        "compiler_output": _dump(item.compiler_output),
                        "confirmed_prompt": item.confirmed_task_prompt,
                        "final_prompt": item.final_prompt,
                        "final_hash": item.final_prompt_sha256,
                    },
                )
                for ordinal in range(1, item.requested_image_count + 1):
                    await session.execute(
                        text(
                            "INSERT INTO project_workbench.generation_image_slots "
                            "(id, batch_id, module_task_id, ordinal) "
                            "VALUES (:id, :batch_id, :task_id, :ordinal)"
                        ),
                        {
                            "id": uuid4(),
                            "batch_id": batch_id,
                            "task_id": task_id,
                            "ordinal": ordinal,
                        },
                    )
            await session.execute(
                text(
                    "UPDATE project_workbench.suite_plans SET status='confirmed', "
                    "revision=revision+1, confirm_idempotency_key=:key, "
                    "confirm_fingerprint=:fingerprint, confirmed_snapshot=CAST(:snapshot AS jsonb), "
                    "generation_batch_id=:batch_id, confirmed_at=now(), updated_at=now() "
                    "WHERE id=:plan_id"
                ),
                {
                    "plan_id": plan_id,
                    "key": idempotency_key,
                    "fingerprint": fingerprint,
                    "snapshot": _dump(confirmed_snapshot),
                    "batch_id": batch_id,
                },
            )
            return batch

    async def get_batch(self, batch_id: UUID, workspace_id: UUID) -> GenerationBatchRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": batch_id, "workspace_id": workspace_id},
            )
            data = row.mappings().first()
            return _batch_from_row(data) if data is not None else None

    async def get_latest(self, project_id: UUID, workspace_id: UUID, *, kind: str | None = None) -> GenerationBatchRecord | None:
        async with self.sessions() as session:
            conditions = "project_id=:project_id AND workspace_id=:workspace_id"
            params: dict[str, Any] = {"project_id": project_id, "workspace_id": workspace_id}
            if kind is not None:
                conditions += " AND kind=:kind"
                params["kind"] = kind
            row = await session.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                    f"WHERE {conditions} ORDER BY updated_at DESC, id DESC LIMIT 1"
                ), params,
            )
            data = row.mappings().first()
            return _batch_from_row(data) if data is not None else None

    async def get_by_compile_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> GenerationBatchRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                    "WHERE workspace_id=:workspace_id AND compile_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            data = row.mappings().first()
            return _batch_from_row(data) if data is not None else None

    async def mark_awaiting_confirmation(
        self, batch_id: UUID, workspace_id: UUID, compilations: dict[str, GenerationModuleCompilation]
    ) -> GenerationBatchRecord:
        async with self.sessions() as session, session.begin():
            batch = await self._locked_batch(session, batch_id, workspace_id)
            _require_status(batch.status, "compiling_prompt")
            tasks = await self._tasks(session, batch_id)
            _require_exact_keys(compilations, {task.module_key for task in tasks})
            for task in tasks:
                compilation = compilations[task.module_key]
                await session.execute(
                    text(
                        "UPDATE project_workbench.generation_module_tasks "
                        "SET compiled_task_prompt=:prompt, compiler_output=CAST(:output AS jsonb), updated_at=now() "
                        "WHERE id=:id"
                    ),
                    {"id": task.id, "prompt": compilation.task_prompt, "output": _dump(compilation.compiler_output)},
                )
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_batches SET status='awaiting_confirmation', "
                    f"updated_at=now() WHERE id=:id RETURNING {_BATCH_COLUMNS}"
                ),
                {"id": batch_id},
            )
            return _batch_from_row(row.mappings().one())

    async def confirm_and_enqueue(
        self, batch_id: UUID, workspace_id: UUID, idempotency_key: str,
        fingerprint: str, confirmations: dict[str, GenerationModuleConfirmation],
    ) -> tuple[GenerationBatchRecord, bool]:
        async with self.sessions() as session, session.begin():
            batch = await self._locked_batch(session, batch_id, workspace_id)
            if batch.confirm_idempotency_key == idempotency_key:
                _same_fingerprint(batch.confirm_fingerprint or "", fingerprint)
                return batch, True
            _require_status(batch.status, "awaiting_confirmation")
            conflicting = await session.scalar(
                text(
                    "SELECT id FROM project_workbench.generation_batches "
                    "WHERE workspace_id=:workspace_id AND confirm_idempotency_key=:key"
                ),
                {"workspace_id": workspace_id, "key": idempotency_key},
            )
            if conflicting is not None:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            tasks = await self._tasks(session, batch_id, lock=True)
            _require_exact_keys(confirmations, {task.module_key for task in tasks})
            for task in tasks:
                confirmation = confirmations[task.module_key]
                await session.execute(
                    text(
                        "UPDATE project_workbench.generation_module_tasks SET confirmed_task_prompt=:task_prompt, "
                        "final_prompt=:final_prompt, final_prompt_sha256=:sha256, confirmed_at=now(), updated_at=now() "
                        "WHERE id=:id"
                    ),
                    {"id": task.id, "task_prompt": confirmation.task_prompt,
                     "final_prompt": confirmation.final_prompt, "sha256": confirmation.final_prompt_sha256},
                )
                for ordinal in range(1, task.requested_image_count + 1):
                    await session.execute(
                        text(
                            "INSERT INTO project_workbench.generation_image_slots "
                            "(id, batch_id, module_task_id, ordinal) VALUES (:id, :batch_id, :task_id, :ordinal)"
                        ),
                        {"id": uuid4(), "batch_id": batch_id, "task_id": task.id, "ordinal": ordinal},
                    )
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_batches SET status='queued', "
                    "confirm_idempotency_key=:key, confirm_fingerprint=:fingerprint, "
                    f"confirmed_at=now(), updated_at=now() WHERE id=:id RETURNING {_BATCH_COLUMNS}"
                ),
                {"id": batch_id, "key": idempotency_key, "fingerprint": fingerprint},
            )
            return _batch_from_row(row.mappings().one()), False

    async def get_batch_detail(self, batch_id: UUID, workspace_id: UUID) -> GenerationBatchDetail | None:
        async with self.sessions() as session:
            batch = await self.get_batch(batch_id, workspace_id)
            if batch is None:
                return None
            tasks = await self._tasks(session, batch_id)
            slots = await self._slots(session, batch_id)
            return GenerationBatchDetail(batch, tasks, slots, _progress(slots))

    async def claim_queued_slots(
        self, worker_id: str, *, limit: int, lease_duration: timedelta,
        now: datetime | None = None,
    ) -> list[GenerationImageSlotRecord]:
        if limit < 1:
            return []
        claimed_at = now or datetime.now(timezone.utc)
        expires_at = claimed_at + lease_duration
        async with self.sessions() as session, session.begin():
            rows = await session.execute(
                text(
                    "WITH candidates AS ("
                    " SELECT slot.id FROM project_workbench.generation_image_slots slot "
                    " JOIN project_workbench.generation_module_tasks module "
                    " ON module.id=slot.module_task_id "
                    " JOIN project_workbench.generation_batches batch ON batch.id=slot.batch_id "
                    " WHERE slot.status='queued' "
                    " ORDER BY batch.created_at, module.position, slot.ordinal, slot.id "
                    " LIMIT :limit FOR UPDATE OF slot SKIP LOCKED"
                    "), claimed AS ("
                    " UPDATE project_workbench.generation_image_slots slot "
                    " SET status='leased', lease_token=gen_random_uuid(), lease_expires_at=:expires_at, "
                    " updated_at=:claimed_at FROM candidates "
                    " WHERE slot.id=candidates.id RETURNING "
                    " slot.id, slot.batch_id, slot.module_task_id, slot.ordinal, slot.status, "
                    " slot.generated_asset_id, slot.lease_token, slot.lease_expires_at, "
                    " slot.provider_idempotency_key, slot.error_code, slot.error_message, "
                    " slot.created_at, slot.updated_at, slot.dispatched_at, slot.completed_at"
                    ") SELECT claimed.id, claimed.batch_id, claimed.module_task_id, module.module_key, "
                    "claimed.ordinal, claimed.status, claimed.generated_asset_id, claimed.lease_token, "
                    "claimed.lease_expires_at, claimed.provider_idempotency_key, claimed.error_code, "
                    "claimed.error_message, claimed.created_at, claimed.updated_at, "
                    "claimed.dispatched_at, claimed.completed_at FROM claimed "
                    "JOIN project_workbench.generation_module_tasks module "
                    "ON module.id=claimed.module_task_id"
                ),
                {"limit": limit, "expires_at": expires_at, "claimed_at": claimed_at},
            )
            slots = [_slot_from_row(row) for row in rows.mappings().all()]
            for slot in slots:
                attempt_no = await session.scalar(
                    text(
                        "SELECT COALESCE(MAX(attempt_no), 0) + 1 "
                        "FROM project_workbench.generation_slot_attempts WHERE slot_id=:slot_id"
                    ),
                    {"slot_id": slot.id},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_slot_attempts "
                        "(id, slot_id, attempt_no, lease_token, worker_id, created_at, updated_at) "
                        "VALUES (:id, :slot_id, :attempt_no, :lease_token, :worker_id, :created_at, :updated_at)"
                    ),
                    {"id": uuid4(), "slot_id": slot.id, "attempt_no": attempt_no,
                     "lease_token": slot.lease_token, "worker_id": worker_id,
                     "created_at": claimed_at, "updated_at": claimed_at},
                )
            await self._refresh_batches(session, {slot.batch_id for slot in slots}, claimed_at)
            return slots

    async def mark_dispatching(
        self,
        slot_id: UUID,
        lease_token: UUID | None,
        now: datetime | None = None,
        *,
        provider_request_summary: dict[str, Any] | None = None,
    ) -> GenerationImageSlotRecord:
        dispatched_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "WITH updated AS ("
                    " UPDATE project_workbench.generation_image_slots SET status='dispatching', "
                    " dispatched_at=:dispatched_at, updated_at=:dispatched_at "
                    " WHERE id=:id AND status='leased' AND lease_token=:lease_token "
                    " RETURNING id"
                    ") SELECT " + _SLOT_COLUMNS + " FROM project_workbench.generation_image_slots slot "
                    "JOIN project_workbench.generation_module_tasks module ON module.id=slot.module_task_id "
                    "JOIN updated ON updated.id=slot.id"
                ),
                {"id": slot_id, "lease_token": lease_token, "dispatched_at": dispatched_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            slot = _slot_from_row(data)
            await session.execute(
                text(
                    "UPDATE project_workbench.generation_slot_attempts SET status='dispatching', "
                    "provider_request_summary=CAST(:summary AS jsonb), dispatched_at=:at, updated_at=:at "
                    "WHERE slot_id=:slot_id AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "at": dispatched_at,
                 "summary": _dump(provider_request_summary or {})},
            )
            await self._refresh_batches(session, {slot.batch_id}, dispatched_at)
            return slot

    async def get_slot_execution(self, slot_id: UUID) -> GenerationSlotExecution | None:
        async with self.sessions() as session:
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                return None
            batch_row = await session.execute(
                text(f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches WHERE id=:id"),
                {"id": slot.batch_id},
            )
            task_row = await session.execute(
                text(f"SELECT {_MODULE_COLUMNS} FROM project_workbench.generation_module_tasks WHERE id=:id"),
                {"id": slot.module_task_id},
            )
            batch_data = batch_row.mappings().first()
            task_data = task_row.mappings().first()
            if batch_data is None or task_data is None:
                return None
            return GenerationSlotExecution(
                _batch_from_row(batch_data), _module_from_row(task_data), slot
            )

    async def complete_slot(
        self, slot_id: UUID, lease_token: UUID | None, generated_asset_id: UUID,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        completed_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='succeeded', "
                    "generated_asset_id=:asset_id, lease_token=NULL, lease_expires_at=NULL, "
                    "completed_at=:at, updated_at=:at WHERE id=:id AND status='dispatching' "
                    "AND lease_token=:lease_token RETURNING batch_id"
                ),
                {"id": slot_id, "asset_id": generated_asset_id, "lease_token": lease_token, "at": completed_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            await session.execute(
                text(
                    "UPDATE project_workbench.generation_slot_attempts SET status='succeeded', "
                    "completed_at=:at, updated_at=:at WHERE slot_id=:slot_id AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "at": completed_at},
            )
            await self._refresh_batches(session, {data["batch_id"]}, completed_at)
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
            return slot

    async def fail_slot(
        self, slot_id: UUID, lease_token: UUID | None, code: str, message: str,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        completed_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='failed', "
                    "error_code=:code, error_message=:message, lease_token=NULL, lease_expires_at=NULL, "
                    "completed_at=:at, updated_at=:at WHERE id=:id AND status='dispatching' "
                    "AND lease_token=:lease_token RETURNING batch_id"
                ),
                {"id": slot_id, "code": code, "message": message, "lease_token": lease_token, "at": completed_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            await session.execute(
                text(
                    "UPDATE project_workbench.generation_slot_attempts SET status='failed', error_code=:code, "
                    "error_message=:message, completed_at=:at, updated_at=:at "
                    "WHERE slot_id=:slot_id AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "code": code, "message": message, "at": completed_at},
            )
            await self._refresh_batches(session, {data["batch_id"]}, completed_at)
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
            return slot

    async def mark_needs_retry(
        self, slot_id: UUID, lease_token: UUID | None, code: str, message: str,
        now: datetime | None = None,
    ) -> GenerationImageSlotRecord:
        marked_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='needs_retry', "
                    "error_code=:code, error_message=:message, lease_token=NULL, lease_expires_at=NULL, "
                    "completed_at=:at, updated_at=:at WHERE id=:id AND status='dispatching' "
                    "AND lease_token=:lease_token RETURNING batch_id"
                ),
                {"id": slot_id, "code": code, "message": message, "lease_token": lease_token, "at": marked_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            await session.execute(
                text(
                    "UPDATE project_workbench.generation_slot_attempts SET status='needs_retry', "
                    "error_code=:code, error_message=:message, completed_at=:at, updated_at=:at "
                    "WHERE slot_id=:slot_id AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "code": code, "message": message, "at": marked_at},
            )
            await self._refresh_batches(session, {data["batch_id"]}, marked_at)
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
            return slot

    async def cancel_batch(
        self, batch_id: UUID, workspace_id: UUID, now: datetime | None = None
    ) -> GenerationBatchRecord:
        cancelled_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            await self._locked_batch(session, batch_id, workspace_id)
            cancelled_rows = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='cancelled', "
                    "lease_token=NULL, lease_expires_at=NULL, completed_at=:at, updated_at=:at "
                    "WHERE batch_id=:batch_id AND status IN ('queued', 'leased') RETURNING id"
                ),
                {"batch_id": batch_id, "at": cancelled_at},
            )
            cancelled_ids = [row["id"] for row in cancelled_rows.mappings().all()]
            if cancelled_ids:
                await session.execute(
                    text(
                        "UPDATE project_workbench.generation_slot_attempts SET status='cancelled', "
                        "completed_at=:at, updated_at=:at WHERE slot_id = ANY(:slot_ids) "
                        "AND status='leased'"
                    ),
                    {"slot_ids": cancelled_ids, "at": cancelled_at},
                )
            dispatching = await session.scalar(
                text(
                    "SELECT count(*) FROM project_workbench.generation_image_slots "
                    "WHERE batch_id=:batch_id AND status IN ('dispatching', 'cancel_requested')"
                ),
                {"batch_id": batch_id},
            )
            if dispatching:
                await session.execute(
                    text(
                        "UPDATE project_workbench.generation_image_slots SET status='cancel_requested', "
                        "updated_at=:at WHERE batch_id=:batch_id AND status='dispatching'"
                    ),
                    {"batch_id": batch_id, "at": cancelled_at},
                )
            status = "cancel_requested" if dispatching else "cancelled"
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_batches SET status=:status, updated_at=:at, "
                    "completed_at=CASE WHEN :is_cancelled THEN :at ELSE completed_at END "
                    f"WHERE id=:id RETURNING {_BATCH_COLUMNS}"
                ),
                {"id": batch_id, "status": status, "is_cancelled": not bool(dispatching), "at": cancelled_at},
            )
            return _batch_from_row(row.mappings().one())

    async def retry_slot(
        self, slot_id: UUID, workspace_id: UUID, now: datetime | None = None
    ) -> GenerationImageSlotRecord:
        retried_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots slot SET status='queued', "
                    "lease_token=NULL, lease_expires_at=NULL, error_code=NULL, error_message=NULL, "
                    "completed_at=NULL, updated_at=:at FROM project_workbench.generation_batches batch "
                    "WHERE slot.id=:slot_id AND slot.batch_id=batch.id AND batch.workspace_id=:workspace_id "
                    "AND slot.status IN ('failed', 'cancelled', 'needs_retry') RETURNING slot.batch_id"
                ),
                {"slot_id": slot_id, "workspace_id": workspace_id, "at": retried_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            await self._refresh_batches(session, {data["batch_id"]}, retried_at)
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
            return slot

    async def is_slot_cancel_requested(self, slot_id: UUID, lease_token: UUID | None) -> bool:
        async with self.sessions() as session:
            return bool(await session.scalar(
                text(
                    "SELECT 1 FROM project_workbench.generation_image_slots "
                    "WHERE id=:slot_id AND status='cancel_requested' AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token},
            ))

    async def complete_cancelled_slot(
        self, slot_id: UUID, lease_token: UUID | None, now: datetime | None = None
    ) -> GenerationImageSlotRecord:
        completed_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='cancelled', "
                    "lease_token=NULL, lease_expires_at=NULL, completed_at=:at, updated_at=:at "
                    "WHERE id=:slot_id AND status='cancel_requested' AND lease_token=:lease_token "
                    "RETURNING batch_id"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "at": completed_at},
            )
            data = row.mappings().first()
            if data is None:
                _invalid_state()
            await session.execute(
                text(
                    "UPDATE project_workbench.generation_slot_attempts SET status='cancelled', "
                    "completed_at=:at, updated_at=:at WHERE slot_id=:slot_id AND lease_token=:lease_token"
                ),
                {"slot_id": slot_id, "lease_token": lease_token, "at": completed_at},
            )
            await self._refresh_batches(session, {data["batch_id"]}, completed_at)
            slot = await self._slot_by_id(session, slot_id)
            if slot is None:
                raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
            return slot

    async def renew_slot_lease(
        self, slot_id: UUID, lease_token: UUID, *, lease_duration: timedelta,
        now: datetime | None = None,
    ) -> bool:
        renewed_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET lease_expires_at=:expires "
                    "WHERE id=:id AND lease_token=:token "
                    "AND lease_expires_at > :renewed_at "
                    "AND status IN ('leased','dispatching','cancel_requested') RETURNING id"
                ),
                {"id": slot_id, "token": lease_token,
                 "expires": renewed_at + lease_duration, "renewed_at": renewed_at},
            )
            return result.first() is not None

    async def recover_expired_leases(self, now: datetime | None = None) -> int:
        recovered_at = now or datetime.now(timezone.utc)
        async with self.sessions() as session, session.begin():
            leased_rows = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='queued', lease_token=NULL, "
                    "lease_expires_at=NULL, updated_at=:at WHERE status='leased' "
                    "AND lease_expires_at <= :at RETURNING id, batch_id"
                ),
                {"at": recovered_at},
            )
            dispatched_rows = await session.execute(
                text(
                    "UPDATE project_workbench.generation_image_slots SET status='needs_retry', lease_token=NULL, "
                    "lease_expires_at=NULL, error_code='PROVIDER_DISPATCH_UNKNOWN', "
                    "error_message='生图请求结果不确定，需要人工重试', completed_at=:at, updated_at=:at "
                    "WHERE status='dispatching' AND lease_expires_at <= :at RETURNING id, batch_id"
                ),
                {"at": recovered_at},
            )
            dispatched = dispatched_rows.mappings().all()
            for row in dispatched:
                await session.execute(
                    text(
                        "UPDATE project_workbench.generation_slot_attempts SET status='needs_retry', "
                        "error_code='PROVIDER_DISPATCH_UNKNOWN', "
                        "error_message='生图请求结果不确定，需要人工重试', completed_at=:at, "
                        "updated_at=:at WHERE slot_id=:slot_id AND status='dispatching'"
                    ),
                    {"slot_id": row["id"], "at": recovered_at},
                )
            leased = leased_rows.mappings().all()
            batch_ids = {row["batch_id"] for row in [*leased, *dispatched]}
            await self._refresh_batches(session, batch_ids, recovered_at)
            return len(leased) + len(dispatched)

    async def list_attempts(self, slot_id: UUID, workspace_id: UUID) -> list[GenerationSlotAttemptRecord]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT attempt.* FROM project_workbench.generation_slot_attempts attempt "
                    "JOIN project_workbench.generation_image_slots slot ON slot.id=attempt.slot_id "
                    "JOIN project_workbench.generation_batches batch ON batch.id=slot.batch_id "
                    "WHERE attempt.slot_id=:slot_id AND batch.workspace_id=:workspace_id "
                    "ORDER BY attempt.attempt_no"
                ),
                {"slot_id": slot_id, "workspace_id": workspace_id},
            )
            return [_attempt_from_row(row) for row in rows.mappings().all()]

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(await session.scalar(text(
                    "SELECT to_regclass('project_workbench.generation_batches') IS NOT NULL"
                )))
        except Exception:
            return False

    async def _locked_batch(
        self, session: AsyncSession, batch_id: UUID, workspace_id: UUID
    ) -> GenerationBatchRecord:
        row = await session.execute(
            text(
                f"SELECT {_BATCH_COLUMNS} FROM project_workbench.generation_batches "
                "WHERE id=:id AND workspace_id=:workspace_id FOR UPDATE"
            ),
            {"id": batch_id, "workspace_id": workspace_id},
        )
        data = row.mappings().first()
        if data is None:
            raise AppError("BATCH_GENERATION_NOT_FOUND", "批次生成任务不存在", 404)
        return _batch_from_row(data)

    async def _tasks(
        self, session: AsyncSession, batch_id: UUID, lock: bool = False
    ) -> list[GenerationModuleTaskRecord]:
        suffix = " FOR UPDATE" if lock else ""
        rows = await session.execute(text(
            f"SELECT {_MODULE_COLUMNS} FROM project_workbench.generation_module_tasks "
            "WHERE batch_id=:batch_id ORDER BY position" + suffix
        ), {"batch_id": batch_id})
        return [_module_from_row(row) for row in rows.mappings().all()]

    async def _slots(self, session: AsyncSession, batch_id: UUID) -> list[GenerationImageSlotRecord]:
        rows = await session.execute(text(
            "SELECT " + _SLOT_COLUMNS + " FROM project_workbench.generation_image_slots slot "
            "JOIN project_workbench.generation_module_tasks module ON module.id=slot.module_task_id "
            "WHERE slot.batch_id=:batch_id ORDER BY module.position, slot.ordinal"
        ), {"batch_id": batch_id})
        return [_slot_from_row(row) for row in rows.mappings().all()]

    async def _slot_by_id(
        self, session: AsyncSession, slot_id: UUID
    ) -> GenerationImageSlotRecord | None:
        row = await session.execute(text(
            "SELECT " + _SLOT_COLUMNS + " FROM project_workbench.generation_image_slots slot "
            "JOIN project_workbench.generation_module_tasks module ON module.id=slot.module_task_id "
            "WHERE slot.id=:slot_id"
        ), {"slot_id": slot_id})
        data = row.mappings().first()
        return _slot_from_row(data) if data is not None else None

    async def _refresh_batches(
        self, session: AsyncSession, batch_ids: set[UUID], now: datetime
    ) -> None:
        for batch_id in batch_ids:
            rows = await self._slots(session, batch_id)
            progress = _progress(rows)
            if progress.dispatching:
                status = "running"
            elif progress.queued or progress.leased:
                status = "queued"
            elif progress.needs_retry or progress.failed:
                status = "partially_failed" if progress.succeeded else "failed"
            elif progress.cancelled:
                status = "cancelled"
            elif progress.total and progress.succeeded == progress.total:
                status = "succeeded"
            else:
                continue
            await session.execute(text(
                "UPDATE project_workbench.generation_batches "
                "SET status=CAST(:status AS varchar), updated_at=:at, "
                "completed_at=CASE WHEN CAST(:status AS varchar) "
                "IN ('succeeded', 'partially_failed', 'failed', 'cancelled') "
                "THEN :at ELSE completed_at END WHERE id=:id"
            ), {"id": batch_id, "status": status, "at": now})


_BATCH_COLUMNS = (
    "id, workspace_id, project_id, source_asset_id, kind, source_plan_id, status, compile_idempotency_key, "
    "compile_fingerprint, confirm_idempotency_key, confirm_fingerprint, snapshot, error_code, "
    "error_message, created_at, updated_at, confirmed_at, completed_at"
)
_MODULE_COLUMNS = (
    "id, batch_id, module_key, position, requested_image_count, snapshot, compiled_task_prompt, "
    "compiler_output, confirmed_task_prompt, final_prompt, final_prompt_sha256, created_at, "
    "updated_at, confirmed_at"
)
_SLOT_COLUMNS = (
    "slot.id, slot.batch_id, slot.module_task_id, module.module_key, slot.ordinal, slot.status, "
    "slot.generated_asset_id, slot.lease_token, slot.lease_expires_at, slot.provider_idempotency_key, "
    "slot.error_code, slot.error_message, slot.created_at, slot.updated_at, slot.dispatched_at, slot.completed_at"
)


def _batch_from_row(row: Any) -> GenerationBatchRecord:
    return GenerationBatchRecord(
        id=row["id"], workspace_id=row["workspace_id"], project_id=row["project_id"],
        source_asset_id=row["source_asset_id"], status=row["status"],
        kind=row["kind"], source_plan_id=row["source_plan_id"],
        compile_idempotency_key=row["compile_idempotency_key"], compile_fingerprint=row["compile_fingerprint"],
        snapshot=_json_value(row["snapshot"]), confirm_idempotency_key=row["confirm_idempotency_key"],
        confirm_fingerprint=row["confirm_fingerprint"], error_code=row["error_code"],
        error_message=row["error_message"], created_at=row["created_at"], updated_at=row["updated_at"],
        confirmed_at=row["confirmed_at"], completed_at=row["completed_at"],
    )


def _module_from_row(row: Any) -> GenerationModuleTaskRecord:
    return GenerationModuleTaskRecord(
        id=row["id"], batch_id=row["batch_id"], module_key=row["module_key"],
        position=row["position"], requested_image_count=row["requested_image_count"], snapshot=_json_value(row["snapshot"]),
        compiled_task_prompt=row["compiled_task_prompt"], compiler_output=_json_value(row["compiler_output"]),
        confirmed_task_prompt=row["confirmed_task_prompt"], final_prompt=row["final_prompt"],
        final_prompt_sha256=row["final_prompt_sha256"], created_at=row["created_at"],
        updated_at=row["updated_at"], confirmed_at=row["confirmed_at"],
    )


def _slot_from_row(row: Any) -> GenerationImageSlotRecord:
    return GenerationImageSlotRecord(
        id=row["id"], batch_id=row["batch_id"], module_task_id=row["module_task_id"],
        module_key=row["module_key"], ordinal=row["ordinal"], status=row["status"],
        generated_asset_id=row["generated_asset_id"], lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"], provider_idempotency_key=row["provider_idempotency_key"],
        error_code=row["error_code"], error_message=row["error_message"], created_at=row["created_at"],
        updated_at=row["updated_at"], dispatched_at=row["dispatched_at"], completed_at=row["completed_at"],
    )


def _attempt_from_row(row: Any) -> GenerationSlotAttemptRecord:
    return GenerationSlotAttemptRecord(
        id=row["id"], slot_id=row["slot_id"], attempt_no=row["attempt_no"], status=row["status"],
        lease_token=row["lease_token"], worker_id=row["worker_id"],
        provider_request_summary=_json_value(row["provider_request_summary"]),
        error_code=row["error_code"], error_message=row["error_message"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        dispatched_at=row["dispatched_at"], completed_at=row["completed_at"],
    )


def _progress(slots: list[GenerationImageSlotRecord]) -> GenerationBatchProgress:
    states = [slot.status for slot in slots]
    return GenerationBatchProgress(
        total=len(states), queued=states.count("queued"), leased=states.count("leased"),
        dispatching=states.count("dispatching"), succeeded=states.count("succeeded"),
        failed=states.count("failed"), cancelled=states.count("cancelled"),
        needs_retry=states.count("needs_retry"),
    )


def _validate_module_inputs(module_inputs: list[GenerationModuleInput]) -> None:
    keys = [item.module_key.strip() for item in module_inputs]
    if not keys or len(keys) != len(set(keys)) or any(not key for key in keys):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "批次模块参数无效", 400)
    if any(item.requested_image_count not in {1, 2, 3, 4} for item in module_inputs):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "模块生成数量无效", 400)


def _validate_confirmed_module_inputs(
    module_inputs: list[ConfirmedGenerationModuleInput],
) -> None:
    keys = [item.module_key.strip() for item in module_inputs]
    positions = [item.position for item in module_inputs]
    if not keys or len(keys) != len(set(keys)) or any(not key for key in keys):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "套图批次模块参数无效", 400)
    if positions != list(range(1, len(module_inputs) + 1)):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "套图批次模块顺序必须连续", 400)
    if any(item.requested_image_count not in {1, 2, 3, 4} for item in module_inputs):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "模块生成数量无效", 400)
    if any(
        not item.compiled_task_prompt.strip()
        or not item.confirmed_task_prompt.strip()
        or not item.final_prompt.strip()
        or len(item.final_prompt_sha256) != 64
        for item in module_inputs
    ):
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "套图批次提示词快照不完整", 400)


def _require_exact_keys(values: dict[str, Any], expected: set[str]) -> None:
    if set(values) != expected:
        raise AppError("BATCH_GENERATION_INVALID_INPUT", "批次模块信息不完整", 400)


def _same_fingerprint(actual: str, expected: str) -> None:
    if actual != expected:
        raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)


def _require_status(actual: str, expected: str) -> None:
    if actual != expected:
        _invalid_state()


def _invalid_state() -> None:
    raise AppError("BATCH_GENERATION_INVALID_STATE", "批次生成任务当前状态不允许此操作", 409)


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_value(value: Any) -> dict[str, Any] | None:
    if value is None or isinstance(value, dict):
        return deepcopy(value)
    return json.loads(value)


def _copy(value: Any) -> Any:
    return deepcopy(value)
