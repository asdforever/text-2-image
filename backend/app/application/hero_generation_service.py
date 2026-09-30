from .style_seed_catalog import resolve_marketplace_style_seed
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from .runtime_module_catalog import runtime_module_catalog, runtime_catalog_snapshot
from .hero_generation_ports import ImageEditRequest, PromptCompileRequest
from .hero_prompting import (
    ConstraintCard,
    ConstraintCards,
    resolve_constraint_cards,
)
from .idempotency import request_fingerprint
from .hero_prompting import resolve_module_prompt
from .design_knowledge import design_knowledge_context, load_design_knowledge
from .module_planning_v2 import (
    PLANNER_VERSION_V2,
    build_v2_compiler_prompts,
    freeze_v2_module_planning,
    normalize_custom_style,
    parse_v2_result,
    render_v2_module_prompt,
    render_v2_from_snapshot,
    compose_v2_from_snapshot,
)


@dataclass(frozen=True)
class HeroPromptCompilationInput:
    source_asset_id: UUID
    market_id: str
    model_id: str
    style_id: str
    module_id: str
    aspect_ratio: str
    resolution: str
    output_language: str
    custom_style: str = ""
    module_parameters: list[dict[str, str]] = field(default_factory=list)
    result_count: int = 1


class HeroGenerationService:
    def __init__(
        self,
        *,
        project_repository: Any,
        project_storage: Any,
        project_asset_service: Any | None = None,
        generation_config_service: Any,
        prompt_repository: Any,
        task_repository: Any,
        prompt_compiler: Any,
        image_editor: Any | None = None,
        identity_provider: Any,
        provider_model: str,
        model_connections: Any | None = None,
        prompt_models: Any | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.project_storage = project_storage
        self.project_asset_service = project_asset_service
        self.generation_config_service = generation_config_service
        self.prompt_repository = prompt_repository
        self.task_repository = task_repository
        self.prompt_compiler = prompt_compiler
        self.image_editor = image_editor
        self.identity_provider = identity_provider
        self.provider_model = provider_model
        self.model_connections = model_connections
        self.prompt_models = prompt_models

    async def compile_prompt(
        self,
        project_id: UUID,
        request: HeroPromptCompilationInput,
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "idempotency key is required", 400)
        fingerprint = request_fingerprint(asdict(request))
        replay = await self.task_repository.get_by_compile_idempotency(
            workspace_id, idempotency_key
        )
        if replay is not None:
            if replay.compile_fingerprint != fingerprint:
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "idempotency key was already used for a different request",
                    409,
                )
            return replay
        if request.result_count != 1:
            raise AppError(
                "HERO_GENERATION_SINGLE_RESULT_REQUIRED",
                "stage 3A requires exactly one generated image",
                400,
            )

        project = await self.project_repository.get_project(project_id, workspace_id)
        if project is None or project.status != "active":
            raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
        # 原图、白底图和生成结果都可以作为生成输入，只校验归属与可用状态。
        asset = await self.project_repository.get_asset(request.source_asset_id, workspace_id)
        if (
            asset is None
            or asset.project_id != project_id
            or asset.state != "available"
        ):
            raise AppError(
                "INVALID_SOURCE_ASSET",
                "source asset does not belong to the active project",
                400,
            )
        source_object = await self.project_repository.get_object(asset.object_id, workspace_id)
        if source_object is None or source_object.state != "available":
            raise AppError("INVALID_SOURCE_ASSET", "source image is unavailable", 400)

        published = await self.generation_config_service.get_published()
        config = published.content
        market = _find_item(config.get("markets"), request.market_id, "电商平台")
        model = _find_item(config.get("models"), request.model_id, "生图模型")
        connection = await self.model_connections.snapshot(model) if self.model_connections else None
        if connection is None and str(model.get("provider", "")).casefold() != "openai":
            raise AppError(
                "GENERATION_MODEL_UNSUPPORTED",
                "selected model preset is not supported by the configured image provider",
                400,
            )
        if request.resolution not in model.get("resolutions", []):
            raise AppError(
                "GENERATION_CONFIG_SELECTION_INVALID",
                "分辨率不属于所选模型",
                400,
            )
        if model.get("aspectRatios") and request.aspect_ratio not in model["aspectRatios"]:
            raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "图片比例不属于所选模型", 400)
        if self.image_editor is not None:
            self.image_editor.describe_request(
                ImageEditRequest(
                    prompt="",
                    image_bytes=b"",
                    image_mime_type="image/png",
                    image_filename="source.png",
                    aspect_ratio=request.aspect_ratio,
                    resolution=request.resolution,
                    model_connection=connection,
                )
            )
        style = _find_style(config.get("styleCategories"), request.style_id)
        custom_style = normalize_custom_style(request.custom_style)
        style_seed = (await resolve_marketplace_style_seed(style, self.prompt_repository))
        module = _find_item(runtime_module_catalog(config, "hero"), request.module_id, "主图模块")
        if module.get("mode") != "hero":
            raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "主图模块选择无效", 400)
        parameters = _normalize_parameters(request.module_parameters)
        cards = await resolve_constraint_cards(
            config,
            market_id=request.market_id,
            style_id=request.style_id,
            prompt_repository=self.prompt_repository,
            style_seed=style_seed.text,
        )
        module_prompt = await resolve_module_prompt(
            config, mode="hero", module_id=request.module_id,
            prompt_repository=self.prompt_repository,
        )
        system_prompt, user_prompt, compiler_snapshot = build_v2_compiler_prompts(
                seed=style_seed,
                module=module,
                module_prompt=module_prompt,
                module_parameters=parameters,
                custom_style=custom_style,
                placement="primary",
                task_outline=None,
                market=market,
                output={
                    "aspectRatio": request.aspect_ratio,
                    "resolution": request.resolution,
                    "language": request.output_language,
                },
                constraints={
                    "productAuthenticity": cards.authenticity.content,
                    "market": cards.market.content,
                },
            )
        stored = await self.project_storage.get(source_object.storage_key)
        if stored is None:
            raise AppError("OBJECT_NOT_FOUND", "source image object does not exist", 404)
        if stored.content_type != source_object.media_type:
            raise AppError("INVALID_SOURCE_ASSET", "source image metadata is inconsistent", 409)

        bound = await self.prompt_models.bind(config, self.prompt_compiler) if self.prompt_models else None
        prompt_compiler = bound.compiler if bound else self.prompt_compiler
        prompt_connection = bound.snapshot if bound else None
        snapshot = {
            "runtimeModules": runtime_catalog_snapshot(config),
            "plannerVersion": PLANNER_VERSION_V2,
            "designKnowledge": design_knowledge_context(load_design_knowledge()),
            "styleSeed": style_seed.to_snapshot(),
            **({"promptModelConnection": prompt_connection} if prompt_connection else {}),
            "sourceAsset": {
                "assetId": str(asset.id),
                "objectId": str(source_object.id),
                "filename": source_object.original_filename,
                "mediaType": source_object.media_type,
                "byteSize": source_object.byte_size,
                "width": source_object.width,
                "height": source_object.height,
                "sha256": source_object.sha256,
            },
            "generationConfig": {
                "version": published.version_no,
                "contentSha256": published.content_sha256,
            },
            "selection": {
                "market": market,
                "modelPreset": model,
                "providerModel": connection["modelName"] if connection else self.provider_model,
                **({"modelConnection": connection} if connection else {}),
                "style": style,
                "module": module,
                "aspectRatio": request.aspect_ratio,
                "resolution": request.resolution,
                "outputLanguage": request.output_language,
                "customStyle": custom_style,
                "moduleParameters": parameters,
                "resultCount": 1,
            },
            "constraints": cards.to_snapshot(),
            "promptCompiler": compiler_snapshot,
        }
        task, duplicate = await self.task_repository.create_compiling(
            workspace_id,
            project_id,
            request.source_asset_id,
            idempotency_key,
            fingerprint,
            snapshot,
        )
        if duplicate:
            return task
        try:
            result = await prompt_compiler.compile(
                PromptCompileRequest(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    image_bytes=stored.data,
                    image_mime_type=source_object.media_type,
                    planner_version=PLANNER_VERSION_V2,
                )
            )
            result = parse_v2_result(result, error_code="PROMPT_COMPILER_INVALID_RESPONSE")
            rendered_prompt = render_v2_module_prompt(result)
            snapshot["modulePlanning"] = freeze_v2_module_planning(result, rendered_prompt)
            await self.task_repository.save_planning_snapshot(task.id, workspace_id, snapshot)
        except AppError as exc:
            await self.task_repository.fail(task.id, workspace_id, exc.code, exc.message)
            raise
        except Exception:
            await self.task_repository.fail(
                task.id,
                workspace_id,
                "PROMPT_COMPILER_FAILED",
                "prompt compiler request failed",
            )
            raise AppError(
                "PROMPT_COMPILER_FAILED",
                "prompt compiler request failed",
                502,
            ) from None
        compiler_output = result.model_dump()
        compiled_task_prompt = rendered_prompt
        return await self.task_repository.mark_awaiting_confirmation(
            task.id,
            workspace_id,
            compiled_task_prompt=compiled_task_prompt,
            compiler_output=compiler_output,
        )

    async def confirm_generation(
        self,
        project_id: UUID,
        task_id: UUID,
        *,
        task_prompt: str | None,
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        task = await self.task_repository.get_task(task_id, workspace_id)
        if task is None or task.project_id != project_id:
            raise AppError(
                "HERO_GENERATION_NOT_FOUND",
                "hero generation task does not exist",
                404,
            )
        confirmed_prompt = render_v2_from_snapshot(task.snapshot)
        submitted_prompt = confirmed_prompt if task_prompt is None else task_prompt.strip()
        if submitted_prompt != confirmed_prompt:
            raise AppError("HERO_GENERATION_V2_PROMPT_IMMUTABLE", "任务提示词由服务端生成，确认时不能修改", 409)
        if task.compiled_task_prompt != confirmed_prompt:
            raise AppError("MODULE_PLANNING_SNAPSHOT_INVALID", "模块规划提示词与冻结快照不一致", 500)
        if not confirmed_prompt:
            raise AppError(
                "INVALID_HERO_TASK_PROMPT",
                "hero task prompt must not be blank",
                400,
            )
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "idempotency key is required", 400)
        fingerprint = request_fingerprint(
            {"taskId": str(task_id), "taskPrompt": confirmed_prompt}
        )
        if task.confirm_idempotency_key == idempotency_key:
            if task.confirm_fingerprint != fingerprint:
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "idempotency key was already used for a different request",
                    409,
                )
            return task
        if task.status != "awaiting_confirmation":
            raise AppError(
                "HERO_GENERATION_INVALID_STATE",
                "hero generation task is not in the required state",
                409,
            )
        if self.image_editor is None or self.project_asset_service is None:
            raise AppError(
                "IMAGE_PROVIDER_UNAVAILABLE",
                "image provider is not configured",
                503,
            )

        source_asset = await self.project_repository.get_asset(
            task.source_asset_id, workspace_id
        )
        source_object = (
            await self.project_repository.get_object(source_asset.object_id, workspace_id)
            if source_asset is not None
            else None
        )
        if (
            source_asset is None
            or source_asset.project_id != project_id
            or source_object is None
            or source_object.state != "available"
        ):
            raise AppError("INVALID_SOURCE_ASSET", "source image is unavailable", 409)
        stored = await self.project_storage.get(source_object.storage_key)
        if stored is None:
            raise AppError("OBJECT_NOT_FOUND", "source image object does not exist", 404)
        selection = task.snapshot.get("selection", {})
        final_prompt = compose_v2_from_snapshot(task.snapshot)
        edit_request = ImageEditRequest(
            prompt=final_prompt,
            image_bytes=stored.data,
            image_mime_type=source_object.media_type,
            image_filename=source_object.original_filename,
            aspect_ratio=str(selection.get("aspectRatio", "")),
            resolution=str(selection.get("resolution", "")),
            model_connection=selection.get("modelConnection"),
        )
        provider_request = self.image_editor.describe_request(edit_request)
        running, duplicate = await self.task_repository.begin_confirmation(
            task.id,
            workspace_id,
            idempotency_key,
            fingerprint,
            confirmed_task_prompt=confirmed_prompt,
            final_prompt=final_prompt,
            final_prompt_sha256=sha256(final_prompt.encode("utf-8")).hexdigest(),
            provider_request=provider_request,
        )
        if duplicate:
            return running
        generated_asset = None
        try:
            result = await self.image_editor.edit(edit_request)
            generated_asset = await self.project_asset_service.create_generated_asset(
                project_id,
                result.image_bytes,
                result.image_mime_type,
                f"hero-{task.id}.png",
                source_asset_id=task.source_asset_id,
                generation_snapshot_id=task.id,
            )
            return await self.task_repository.complete(
                task.id, workspace_id, generated_asset.id
            )
        except AppError as exc:
            await self._compensate_generated_asset(project_id, generated_asset)
            await self.task_repository.fail(task.id, workspace_id, exc.code, exc.message)
            raise
        except Exception:
            await self._compensate_generated_asset(project_id, generated_asset)
            await self.task_repository.fail(
                task.id,
                workspace_id,
                "HERO_GENERATION_PERSIST_FAILED",
                "generated image could not be persisted",
            )
            raise

    async def get_task(self, project_id: UUID, task_id: UUID):
        workspace_id = self.identity_provider.get_context().workspace_id
        task = await self.task_repository.get_task(task_id, workspace_id)
        if task is None or task.project_id != project_id:
            raise AppError(
                "HERO_GENERATION_NOT_FOUND",
                "hero generation task does not exist",
                404,
            )
        return task

    async def _compensate_generated_asset(self, project_id: UUID, asset: Any | None) -> None:
        if asset is None or self.project_asset_service is None:
            return
        try:
            await self.project_asset_service.delete_asset(project_id, asset.id)
        except Exception:
            pass


def _find_item(items: Any, item_id: str, label: str) -> dict[str, Any]:
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id") == item_id:
                return deepcopy_dict(item)
    raise AppError("GENERATION_CONFIG_SELECTION_INVALID", f"{label}选择无效", 400)


def _find_style(categories: Any, style_id: str) -> dict[str, Any]:
    if isinstance(categories, list):
        for category in categories:
            if not isinstance(category, dict):
                continue
            try:
                return _find_item(category.get("styles"), style_id, "图片风格")
            except AppError:
                continue
    raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "图片风格选择无效", 400)


def _normalize_parameters(parameters: Any) -> list[dict[str, str]]:
    if not isinstance(parameters, list) or len(parameters) > 20:
        raise AppError("INVALID_MODULE_PARAMETERS", "module parameters are invalid", 400)
    normalized = []
    for item in parameters:
        if not isinstance(item, dict):
            raise AppError("INVALID_MODULE_PARAMETERS", "module parameters are invalid", 400)
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or not value or len(key) > 60 or len(value) > 500:
            raise AppError("INVALID_MODULE_PARAMETERS", "module parameters are invalid", 400)
        normalized.append({"key": key, "value": value})
    return normalized


def deepcopy_dict(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _constraint_cards_from_snapshot(value: Any) -> ConstraintCards:
    if not isinstance(value, dict):
        raise AppError("HERO_GENERATION_SNAPSHOT_INVALID", "task snapshot is invalid", 500)
    try:
        return ConstraintCards(
            authenticity=_constraint_card_from_snapshot(value["authenticity"]),
            market=_constraint_card_from_snapshot(value["market"]),
            style=_constraint_card_from_snapshot(value["style"]),
        )
    except (KeyError, TypeError, ValueError):
        raise AppError(
            "HERO_GENERATION_SNAPSHOT_INVALID", "task snapshot is invalid", 500
        ) from None


def _constraint_card_from_snapshot(value: Any) -> ConstraintCard:
    if not isinstance(value, dict) or not str(value.get("content", "")).strip():
        raise ValueError("invalid constraint card")
    return ConstraintCard(
        content=str(value["content"]),
        source=str(value.get("source", "snapshot")),
        content_sha256=str(value.get("contentSha256", "")),
        prompt_template_id=(
            UUID(str(value["promptTemplateId"])) if value.get("promptTemplateId") else None
        ),
        prompt_version_id=(
            UUID(str(value["promptVersionId"])) if value.get("promptVersionId") else None
        ),
        prompt_version_sha256=(
            str(value["promptVersionSha256"])
            if value.get("promptVersionSha256")
            else None
        ),
    )
