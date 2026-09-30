from .regular_design import render_regular
from copy import deepcopy
from hashlib import sha256
from typing import Any
from uuid import UUID

from ..batch_generation_repository import ConfirmedGenerationModuleInput
from ..core.errors import AppError
from .idempotency import request_fingerprint
from .module_planning_v2 import compose_v2_from_snapshot, render_v2_from_snapshot


class SuitePlanningConfirmationService:
    """冻结详情页规划，并从同一快照创建可执行套图批次。"""

    def __init__(self, *, plan_repository: Any, batch_repository: Any, identity_provider: Any) -> None:
        self.plan_repository = plan_repository
        self.batch_repository = batch_repository
        self.identity_provider = identity_provider

    async def confirm_plan(
        self,
        project_id: UUID,
        plan_id: UUID,
        *,
        expected_plan_revision: int,
        module_task_prompts: dict[str, str],
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "幂等键不能为空", 400)
        normalized_prompts = {
            str(module_key).strip(): str(prompt).strip()
            for module_key, prompt in module_task_prompts.items()
        }
        fingerprint = request_fingerprint(
            {"planId": str(plan_id), "moduleTaskPrompts": normalized_prompts}
        )

        replay = await self.plan_repository.get_by_confirm_idempotency(
            workspace_id, idempotency_key
        )
        if replay is not None:
            if replay.confirm_fingerprint != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            if replay.project_id != project_id or replay.id != plan_id or replay.generation_batch_id is None:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            batch = await self.batch_repository.get_batch(
                replay.generation_batch_id, workspace_id
            )
            if batch is None:
                raise AppError("SUITE_PLAN_CONFIRMATION_INCOMPLETE", "规划确认记录不完整", 500)
            return batch

        detail = await self.plan_repository.get_plan_detail(
            plan_id, workspace_id, project_id
        )
        if detail is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        if detail.plan.status != "awaiting_confirmation":
            raise AppError("SUITE_PLAN_NOT_EDITABLE", "详情页规划当前状态不允许确认", 409)
        if detail.plan.revision != expected_plan_revision:
            raise AppError("SUITE_PLAN_REVISION_CONFLICT", "规划已更新，请刷新后重试", 409)
        expected_keys = {module.module_key for module in detail.modules}
        if (
            set(normalized_prompts) != expected_keys
            or any(not prompt for prompt in normalized_prompts.values())
        ):
            raise AppError("SUITE_PLAN_INVALID_INPUT", "模块实时任务提示词不完整", 400)

        module_inputs: list[ConfirmedGenerationModuleInput] = []
        frozen_modules: list[dict[str, Any]] = []
        for module in detail.modules:
            task_prompt = normalized_prompts[module.module_key]
            frozen_prompt = render_regular(module.prompt_snapshot) if module.prompt_snapshot.get("creationMode") == "regular" else render_v2_from_snapshot(module.prompt_snapshot)
            if task_prompt != frozen_prompt:
                raise AppError("V2_PROMPT_READ_ONLY", "提示词不可直接修改，请调整模块参数后重新编译", 400)
            final_prompt = frozen_prompt if module.prompt_snapshot.get("creationMode") == "regular" else compose_v2_from_snapshot(module.prompt_snapshot)
            final_hash = sha256(final_prompt.encode("utf-8")).hexdigest()
            frozen_module = {
                "id": str(module.id),
                "moduleKey": module.module_key,
                "taskId": module.module_key,
                "moduleId": module.prompt_snapshot.get("moduleId") or module.prompt_snapshot.get("module", {}).get("id", module.module_key),
                "position": module.position,
                "requestedImageCount": module.requested_image_count,
                "revision": module.revision,
                "title": module.title,
                "copySummary": module.copy_summary,
                "visualDirection": module.visual_direction,
                "moduleParameters": deepcopy(module.module_parameters),
                "promptSnapshot": deepcopy(module.prompt_snapshot),
                "compiledTaskPrompt": module.compiled_task_prompt,
                "compilerOutput": deepcopy(module.compiler_output or {}),
                "confirmedTaskPrompt": task_prompt,
                "finalPrompt": final_prompt,
                "finalPromptSha256": final_hash,
            }
            frozen_modules.append(frozen_module)
            module_inputs.append(
                ConfirmedGenerationModuleInput(
                    module_key=module.module_key,
                    position=module.position,
                    requested_image_count=module.requested_image_count,
                    snapshot=frozen_module,
                    compiled_task_prompt=module.compiled_task_prompt or "",
                    compiler_output=deepcopy(module.compiler_output or {}),
                    confirmed_task_prompt=task_prompt,
                    final_prompt=final_prompt,
                    final_prompt_sha256=final_hash,
                )
            )

        source_assets = detail.plan.snapshot.get("sourceAssets")
        if not isinstance(source_assets, list) or not source_assets:
            raise AppError("SUITE_PLAN_SNAPSHOT_INVALID", "规划源图快照不完整", 500)
        try:
            source_asset_id = UUID(str(source_assets[0]["assetId"]))
        except (KeyError, TypeError, ValueError):
            raise AppError("SUITE_PLAN_SNAPSHOT_INVALID", "规划源图快照不完整", 500) from None
        confirmed_snapshot = {
            **deepcopy(detail.plan.snapshot),
            "planId": str(detail.plan.id),
            "planRevision": detail.plan.revision,
            "modules": frozen_modules,
        }
        if hasattr(self.batch_repository, "confirm_plan_and_create_batch"):
            return await self.batch_repository.confirm_plan_and_create_batch(
                workspace_id=workspace_id,
                project_id=project_id,
                plan_id=plan_id,
                expected_plan_revision=expected_plan_revision,
                source_asset_id=source_asset_id,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                confirmed_snapshot=confirmed_snapshot,
                module_inputs=module_inputs,
            )

        batch, duplicate = await self.batch_repository.create_confirmed_from_plan(
            workspace_id,
            project_id,
            plan_id,
            source_asset_id,
            idempotency_key,
            fingerprint,
            confirmed_snapshot,
            module_inputs,
        )
        try:
            await self.plan_repository.mark_confirmed(
                plan_id,
                workspace_id,
                project_id,
                expected_plan_revision=expected_plan_revision,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                confirmed_snapshot=confirmed_snapshot,
                generation_batch_id=batch.id,
            )
        except Exception:
            if not duplicate and hasattr(self.batch_repository, "discard_suite_batch"):
                await self.batch_repository.discard_suite_batch(batch.id, workspace_id, plan_id)
            raise
        return batch
