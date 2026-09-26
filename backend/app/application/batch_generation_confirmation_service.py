from hashlib import sha256
from typing import Any
from uuid import UUID

from ..batch_generation_repository import GenerationModuleConfirmation
from ..core.errors import AppError
from .idempotency import request_fingerprint
from .module_planning_v2 import (
    PLANNER_VERSION_V2,
    compose_v2_from_snapshot,
    render_v2_from_snapshot,
)


class BatchGenerationConfirmationService:
    def __init__(self, batch_repository: Any, identity_provider: Any) -> None:
        self.batch_repository = batch_repository
        self.identity_provider = identity_provider

    async def confirm_batch(
        self,
        project_id: UUID,
        batch_id: UUID,
        module_task_prompts: dict[str, str],
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "幂等键不能为空", 400)
        detail = await self.batch_repository.get_batch_detail(batch_id, workspace_id)
        if detail is None or detail.batch.project_id != project_id:
            raise AppError("BATCH_GENERATION_NOT_FOUND", "批次生成任务不存在", 404)
        normalized = {
            module_key: str(prompt).strip()
            for module_key, prompt in module_task_prompts.items()
        }
        expected = {task.module_key for task in detail.module_tasks}
        if set(normalized) != expected or any(not prompt for prompt in normalized.values()):
            raise AppError("BATCH_GENERATION_INVALID_INPUT", "模块实时提示词不完整", 400)
        for task in detail.module_tasks:
            rendered = render_v2_from_snapshot(task.snapshot)
            if task.compiled_task_prompt != rendered:
                raise AppError(
                    "MODULE_PLANNING_SNAPSHOT_INVALID",
                    "V2 模块规划提示词与冻结快照不一致",
                    500,
                )
            if normalized[task.module_key] != rendered:
                raise AppError(
                    "BATCH_GENERATION_V2_PROMPT_IMMUTABLE",
                    "V2 模块提示词由服务端生成，确认时不能修改",
                    409,
                )
        fingerprint = request_fingerprint(
            {"batchId": str(batch_id), "moduleTaskPrompts": normalized}
        )
        confirmations: dict[str, GenerationModuleConfirmation] = {}
        for task in detail.module_tasks:
            task_prompt = normalized[task.module_key]
            final_prompt = compose_v2_from_snapshot(task.snapshot)
            confirmations[task.module_key] = GenerationModuleConfirmation(
                task_prompt=task_prompt,
                final_prompt=final_prompt,
                final_prompt_sha256=sha256(final_prompt.encode("utf-8")).hexdigest(),
            )
        batch, _duplicate = await self.batch_repository.confirm_and_enqueue(
            batch_id,
            workspace_id,
            idempotency_key,
            fingerprint,
            confirmations,
        )
        return batch
