from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any
from uuid import UUID

from ..batch_generation_repository import (
    GenerationModuleCompilation,
    GenerationModuleInput,
)
from ..core.errors import AppError
from .runtime_module_catalog import runtime_module_catalog, runtime_catalog_snapshot
from .hero_generation_ports import ImageEditInput, ImageEditRequest, PromptCompileRequest
from .hero_generation_service import (
    _find_item,
    _find_style,
    _normalize_parameters,
)
from .hero_prompting import resolve_constraint_cards
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
    resolve_style_seed,
    task_outline_from_master,
)


@dataclass(frozen=True)
class BatchHeroModuleInput:
    module_id: str
    result_count: int
    module_parameters: list[dict[str, str]] = field(default_factory=list)
    task_id: str | None = None
    reverse_reference: dict[str, Any] | None = None
    task_design: dict[str, Any] | None = None


@dataclass(frozen=True)
class BatchHeroPromptCompilationInput:
    source_asset_id: UUID
    market_id: str
    model_id: str
    style_id: str
    aspect_ratio: str
    resolution: str
    output_language: str
    modules: list[BatchHeroModuleInput]
    custom_style: str = ""
    module_plan_id: UUID | None = None
    reverse_version_id: UUID | None = None


class BatchHeroPromptCompilationService:
    def __init__(
        self,
        *,
        project_repository: Any,
        project_storage: Any,
        generation_config_service: Any,
        prompt_repository: Any,
        batch_repository: Any,
        prompt_compiler: Any,
        image_editor: Any | None,
        identity_provider: Any,
        provider_model: str,
        model_connections: Any | None = None,
        prompt_models: Any | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.project_storage = project_storage
        self.generation_config_service = generation_config_service
        self.prompt_repository = prompt_repository
        self.batch_repository = batch_repository
        self.prompt_compiler = prompt_compiler
        self.image_editor = image_editor
        self.identity_provider = identity_provider
        self.provider_model = provider_model
        self.model_connections = model_connections
        self.prompt_models = prompt_models
        self.module_planning = None
        self.reverse_projects = None

    async def compile_prompt_batch(
        self,
        project_id: UUID,
        request: BatchHeroPromptCompilationInput,
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "幂等键不能为空", 400)
        self._validate_modules(request.modules)
        fingerprint_input = asdict(request)
        for item in fingerprint_input["modules"]:
            if item["task_id"] is None:
                item.pop("task_id")
            if item.get("reverse_reference") is None:
                item.pop("reverse_reference", None)
        if fingerprint_input.get("reverse_version_id") is None:
            fingerprint_input.pop("reverse_version_id", None)
        fingerprint = request_fingerprint(fingerprint_input)
        replay = await self.batch_repository.get_by_compile_idempotency(
            workspace_id, idempotency_key
        )
        if replay is not None:
            if replay.compile_fingerprint != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            return replay

        project = await self.project_repository.get_project(project_id, workspace_id)
        master_snapshot = None
        if request.module_plan_id:
            if self.module_planning is None:
                raise AppError("MODULE_PLANNER_UNAVAILABLE", "自动规划服务不可用", 503)
            master_snapshot = await self.module_planning.snapshot(project_id, request.module_plan_id, "hero")
        request_reverse_version = str(request.reverse_version_id) if request.reverse_version_id else None
        master_reverse_version = (
            str(master_snapshot.get("input", {}).get("reverseVersionId"))
            if master_snapshot and master_snapshot.get("input", {}).get("reverseVersionId")
            else None
        )
        if master_snapshot is not None and master_reverse_version != request_reverse_version:
            raise AppError(
                "REVERSE_PLANNING_VERSION_MISMATCH",
                "自动规划引用的反推版本与当前请求不一致",
                409,
            )
        if project is None or project.status != "active":
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        reverse_overview = None
        if request.reverse_version_id is not None:
            if self.reverse_projects is None:
                raise AppError("REVERSE_PLANNING_UNAVAILABLE", "反推规划服务不可用", 503)
            reverse_overview = await self.reverse_projects.planning_context(request.reverse_version_id)
        # 原图、白底图和生成结果都可以作为生成输入：白底图是主图/套图的推荐输入，
        # 生成结果用于在已有成品基础上继续迭代。只校验归属与可用状态。
        asset = await self.project_repository.get_asset(request.source_asset_id, workspace_id)
        if (
            asset is None
            or asset.project_id != project_id
            or asset.state != "available"
        ):
            raise AppError("INVALID_SOURCE_ASSET", "源图不属于当前项目", 400)
        source_object = await self.project_repository.get_object(asset.object_id, workspace_id)
        if source_object is None or source_object.state != "available":
            raise AppError("INVALID_SOURCE_ASSET", "源图不可用", 400)

        published = await self.generation_config_service.get_published()
        config = published.content
        market = _find_item(config.get("markets"), request.market_id, "电商平台")
        model = _find_item(config.get("models"), request.model_id, "生图模型")
        connection = await self.model_connections.snapshot(model) if self.model_connections else None
        if connection is None and str(model.get("provider", "")).casefold() != "openai":
            raise AppError("GENERATION_MODEL_UNSUPPORTED", "所选生图模型暂不受支持", 400)
        if request.resolution not in model.get("resolutions", []):
            raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "分辨率不属于所选模型", 400)
        if model.get("aspectRatios") and request.aspect_ratio not in model["aspectRatios"]:
            raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "图片比例不属于所选模型", 400)
        if self.image_editor is not None:
            self.image_editor.describe_request(
                ImageEditRequest(
                    prompt="", image_bytes=b"", image_mime_type="image/png", image_filename="source.png",
                    aspect_ratio=request.aspect_ratio, resolution=request.resolution,
                    model_connection=connection,
                )
            )
        style = _find_style(config.get("styleCategories"), request.style_id)
        custom_style = normalize_custom_style(request.custom_style)
        style_seed = resolve_style_seed(style)
        cards = await resolve_constraint_cards(
            config,
            market_id=request.market_id,
            style_id=request.style_id,
            prompt_repository=self.prompt_repository,
            style_seed=style_seed.text,
        )
        stored = await self.project_storage.get(source_object.storage_key)
        if stored is None:
            raise AppError("OBJECT_NOT_FOUND", "源图对象不存在", 404)
        if stored.content_type != source_object.media_type:
            raise AppError("INVALID_SOURCE_ASSET", "源图元数据不一致", 409)

        bound = await self.prompt_models.bind(config, self.prompt_compiler) if self.prompt_models else None
        prompt_compiler = bound.compiler if bound else self.prompt_compiler
        prompt_connection = bound.snapshot if bound else None
        module_inputs: list[GenerationModuleInput] = []
        planned: list[
            tuple[
                BatchHeroModuleInput,
                dict[str, Any],
                list[dict[str, str]],
                dict[str, Any],
                tuple[ImageEditInput, ...],
            ]
        ] = []
        requested_tasks = [
            {
                "taskId": item.task_id or item.module_id,
                "moduleId": item.module_id,
                "moduleParameters": _normalize_parameters(item.module_parameters),
            }
            for item in request.modules
        ]
        for task_index, selected in enumerate(request.modules):
            module = _find_item(runtime_module_catalog(config, "hero"), selected.module_id, "主图模块")
            if module.get("mode") != "hero":
                raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "主图模块选择无效", 400)
            parameters = _normalize_parameters(selected.module_parameters)
            task_id = selected.task_id or selected.module_id
            task_outline = task_outline_from_master(master_snapshot, task_id, selected.module_id)
            reverse_reference = selected.reverse_reference
            if reverse_reference is None and task_outline and task_outline.get("referenceModuleId"):
                reverse_reference = {
                    "versionId": request.reverse_version_id,
                    "moduleId": task_outline["referenceModuleId"],
                }
            reverse_snapshot = None
            reverse_image_inputs: tuple[ImageEditInput, ...] = ()
            reverse_prompt_context = None
            if reverse_reference is not None:
                if self.reverse_projects is None:
                    raise AppError("REVERSE_PLANNING_UNAVAILABLE", "反推规划服务不可用", 503)
                reference_version = reverse_reference.get("versionId") or reverse_reference.get("version_id")
                reference_module = reverse_reference.get("moduleId") or reverse_reference.get("module_id")
                if not reference_version or not reference_module:
                    raise AppError("REVERSE_PLANNING_REFERENCE_INVALID", "反推模块引用不完整", 400)
                reverse_context = await self.reverse_projects.planning_context(
                    UUID(str(reference_version)), str(reference_module)
                )
                reverse_images, reverse_mimes = await self.reverse_projects.planning_images(
                    UUID(str(reference_version)), str(reference_module)
                )
                reverse_image_inputs = tuple(
                    ImageEditInput(data, mime, f"reverse-reference-{index + 1}")
                    for index, (data, mime) in enumerate(zip(reverse_images, reverse_mimes))
                )
                reverse_prompt_context = {
                    "role": "competitor_design_reference",
                    "factPolicy": (
                        "Use only the reference layout, hierarchy, and visual method; "
                        "current product facts must come from current product assets and constraints."
                    ),
                    "context": reverse_context,
                }
                reverse_snapshot = {
                    **reverse_prompt_context,
                    "imageMimeTypes": list(reverse_mimes),
                }
            master_context = (
                {
                    "summary": master_snapshot.get("summary", ""),
                    "brief": master_snapshot.get("input", {}).get("brief", ""),
                    "tasks": master_snapshot.get("modules", []),
                    "currentTaskId": task_id,
                }
                if master_snapshot else None
            )
            module_prompt = await resolve_module_prompt(
                config, mode="hero", module_id=selected.module_id,
                prompt_repository=self.prompt_repository,
            )
            system_prompt, user_prompt, compiler_snapshot = build_v2_compiler_prompts(
                task_design=selected.task_design,
                seed=style_seed, module=module, module_parameters=parameters,
                module_prompt=module_prompt,
                custom_style=custom_style, task_outline=task_outline, market=market,
                shared_visual_direction=(master_snapshot or {}).get("sharedVisualDirection", ""),
                placement="primary" if task_index == 0 else "gallery",
                output={"aspectRatio": request.aspect_ratio, "resolution": request.resolution, "language": request.output_language},
                constraints={"productAuthenticity": cards.authenticity.content, "market": cards.market.content},
                additional_context={
                    "currentTaskId": task_id,
                    "tasks": requested_tasks,
                    "masterPlanning": master_context,
                    **(
                        {"additionalContext": {
                            **({"reversePlanning": reverse_overview} if reverse_overview else {}),
                            **({"reverseReference": reverse_prompt_context} if reverse_prompt_context else {}),
                        }}
                        if reverse_overview or reverse_prompt_context else {}
                    ),
                },
            )
            module_snapshot = {
                "plannerVersion": PLANNER_VERSION_V2,
                "taskId": task_id,
                "moduleId": selected.module_id,
                "taskDesign": compiler_snapshot["taskDesign"],
                "effectiveTaskOutline": compiler_snapshot["effectiveTaskOutline"],
                "title": (compiler_snapshot["effectiveTaskOutline"] or {}).get("taskTitle") or module.get("label", selected.module_id),
                "styleSeed": style_seed.to_snapshot(),
                **({"taskOutline": task_outline} if task_outline else {}),
                **({"promptModelConnection": prompt_connection} if prompt_connection else {}),
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
                    "resultCount": selected.result_count,
                },
                "constraints": cards.to_snapshot(),
                "promptCompiler": compiler_snapshot,
                **({"reverseReference": reverse_snapshot} if reverse_snapshot else {}),
            }
            module_inputs.append(
                GenerationModuleInput(selected.task_id or selected.module_id, selected.result_count, module_snapshot)
            )
            planned.append(
                (
                    selected,
                    module,
                    parameters,
                    {"system": system_prompt, "user": user_prompt},
                    reverse_image_inputs,
                )
            )

        snapshot = {
            "runtimeModules": runtime_catalog_snapshot(config),
            "plannerVersion": PLANNER_VERSION_V2,
            "designKnowledge": design_knowledge_context(load_design_knowledge()),
            "styleSeed": style_seed.to_snapshot(),
            **({"planningMaster": master_snapshot} if master_snapshot else {}),
            **({"reversePlanning": reverse_overview} if reverse_overview else {}),
            **({"promptModelConnection": prompt_connection} if prompt_connection else {}),
            "sourceAsset": {
                "assetId": str(asset.id), "objectId": str(source_object.id),
                "filename": source_object.original_filename, "mediaType": source_object.media_type,
                "byteSize": source_object.byte_size, "width": source_object.width,
                "height": source_object.height, "sha256": source_object.sha256,
            },
            "generationConfig": {"version": published.version_no, "contentSha256": published.content_sha256},
        }
        batch, duplicate = await self.batch_repository.create_compiling(
            workspace_id, project_id, request.source_asset_id, idempotency_key, fingerprint,
            snapshot, module_inputs,
        )
        if duplicate:
            return batch
        compilations: dict[str, GenerationModuleCompilation] = {}
        for selected, _module, _parameters, prompts, reverse_image_inputs in planned:
            try:
                result = await prompt_compiler.compile(
                    PromptCompileRequest(
                        system_prompt=prompts["system"], user_prompt=prompts["user"],
                        image_bytes=stored.data, image_mime_type=source_object.media_type,
                        planner_version=PLANNER_VERSION_V2,
                        image_inputs=(
                            ImageEditInput(stored.data, source_object.media_type, source_object.original_filename),
                            *reverse_image_inputs,
                        ),
                    )
                )
                result = parse_v2_result(result, error_code="PROMPT_COMPILER_INVALID_RESPONSE")
                module_input = next(item for item in module_inputs if item.module_key == (selected.task_id or selected.module_id))
                rendered = render_v2_module_prompt(result)
                module_input.snapshot["modulePlanning"] = freeze_v2_module_planning(result, rendered)
                await self.batch_repository.save_planning_snapshot(
                    batch.id, workspace_id, snapshot, {item.module_key: item.snapshot for item in module_inputs},
                )
            except AppError as exc:
                await self.batch_repository.mark_failed(batch.id, workspace_id, exc.code, exc.message)
                raise
            except Exception:
                await self.batch_repository.mark_failed(batch.id, workspace_id, "PROMPT_COMPILER_FAILED", "提示词编译服务请求失败")
                raise AppError("PROMPT_COMPILER_FAILED", "提示词编译服务请求失败", 502) from None
            compiler_output = result.model_dump()
            compilations[selected.task_id or selected.module_id] = GenerationModuleCompilation(rendered, compiler_output)
        return await self.batch_repository.mark_awaiting_confirmation(
            batch.id, workspace_id, compilations
        )

    @staticmethod
    def _validate_modules(modules: list[BatchHeroModuleInput]) -> None:
        if any(item.task_id is not None and (item.task_id != item.task_id.strip() or len(item.task_id) > 100) for item in modules):
            raise AppError("BATCH_GENERATION_INVALID_INPUT", "任务标识无效", 400)
        module_ids = [(item.task_id if item.task_id is not None else item.module_id).strip() for item in modules]
        if not 1 <= len(modules) <= 8 or len(module_ids) != len(set(module_ids)) or any(not item or len(item) > 100 for item in module_ids) or any(not item.module_id.strip() for item in modules):
            raise AppError("BATCH_GENERATION_INVALID_INPUT", "批次模块参数无效", 400)
        if any(item.result_count not in {1, 2, 3, 4} for item in modules):
            raise AppError("BATCH_GENERATION_INVALID_INPUT", "模块生成数量无效", 400)
