from .style_seed_catalog import resolve_marketplace_style_seed
from .regular_design import regular_snapshot, RECIPE
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import UUID

from ..core.errors import AppError
from .runtime_module_catalog import runtime_module_catalog, runtime_catalog_snapshot
from ..suite_planning_repository import (
    SuitePlanModuleCompilation,
    SuitePlanModuleInput as RepositoryModuleInput,
)
from .hero_generation_service import _find_item, _find_style, _normalize_parameters
from .hero_prompting import resolve_constraint_cards
from .idempotency import request_fingerprint
from .suite_planning_ports import PlanningReferenceRequest, PlanningReferenceResolver
from .hero_prompting import resolve_module_prompt
from .design_knowledge import design_knowledge_context, load_design_knowledge
from .module_planning_v2 import (
    PLANNER_VERSION_V2, build_v2_compiler_prompts, freeze_v2_module_planning,
    normalize_custom_style, parse_v2_result, render_v2_module_prompt,
    task_outline_from_master,
)


@dataclass(frozen=True)
class SuitePlanModuleInput:
    module_id: str
    result_count: int
    module_parameters: list[dict[str, str]] = field(default_factory=list)
    task_id: str | None = None
    reverse_reference: dict[str, Any] | None = None
    task_design: dict[str, Any] | None = None
    regular_task: dict[str, str] | None = None
    regular_options: dict[str, Any] | None = None


@dataclass(frozen=True)
class SuitePlanCompilationInput:
    source_asset_ids: list[UUID]
    market_id: str
    model_id: str
    style_id: str
    aspect_ratio: str
    resolution: str
    output_language: str
    modules: list[SuitePlanModuleInput]
    user_notes: str = ""
    custom_style: str = ""
    references: list[PlanningReferenceRequest] = field(default_factory=list)
    module_plan_id: UUID | None = None
    planning_applied_version_id: UUID | None = None
    reverse_version_id: UUID | None = None
    creation_mode: Literal["regular", "professional"] = "professional"


@dataclass(frozen=True)
class SuitePlanCompilerRequest:
    module_id: str
    module: dict[str, Any]
    module_parameters: list[dict[str, str]]
    image_inputs: list[bytes]
    image_mime_types: list[str]
    system_prompt: str
    user_prompt: str
    planner_version: Literal["v2"] = "v2"


@dataclass(frozen=True)
class SuitePlanModuleUpdateInput:
    module_id: UUID
    expected_plan_revision: int
    expected_module_revision: int
    title: str | None = None
    copy_summary: str | None = None
    visual_direction: str | None = None
    current_task_prompt: str | None = None
    requested_image_count: int | None = None
    module_parameters: list[dict[str, str]] | None = None


class SuitePlanningService:
    def __init__(
        self,
        *,
        project_repository: Any,
        project_storage: Any,
        generation_config_service: Any,
        prompt_repository: Any,
        plan_repository: Any,
        reference_resolver: PlanningReferenceResolver,
        planner_compiler: Any,
        identity_provider: Any,
        provider_model: str,
        model_connections: Any | None = None,
        prompt_models: Any | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.project_storage = project_storage
        self.generation_config_service = generation_config_service
        self.prompt_repository = prompt_repository
        self.plan_repository = plan_repository
        self.reference_resolver = reference_resolver
        self.planner_compiler = planner_compiler
        self.identity_provider = identity_provider
        self.provider_model = provider_model
        self.model_connections = model_connections
        self.prompt_models = prompt_models
        self.module_planning = None
        self.reverse_projects = None

    async def compile_plan(
        self,
        project_id: UUID,
        request: SuitePlanCompilationInput,
        idempotency_key: str,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        if request.creation_mode != 'regular' and any(m.regular_options is not None for m in request.modules):
            raise AppError('REGULAR_OPTIONS_MODE_MISMATCH', '常规选项不能用于专业模式', 400)
        if not idempotency_key.strip():
            raise AppError("INVALID_IDEMPOTENCY_REQUEST", "幂等键不能为空", 400)
        fingerprint_input = asdict(request)
        if request.planning_applied_version_id is None:
            fingerprint_input.pop('planning_applied_version_id', None)
        for item in fingerprint_input["modules"]:
            if item.get('regular_options') is None:
                item.pop('regular_options', None)
            if item["task_id"] is None:
                item.pop("task_id")
            if item.get("reverse_reference") is None:
                item.pop("reverse_reference", None)
        if fingerprint_input.get("reverse_version_id") is None:
            fingerprint_input.pop("reverse_version_id", None)
        fingerprint = request_fingerprint(fingerprint_input)
        replay = await self.plan_repository.get_by_compile_idempotency(
            workspace_id, idempotency_key
        )
        if replay is not None:
            if replay.compile_fingerprint != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求", 409)
            return replay

        self._validate_request(request)
        if request.planning_applied_version_id:
            conversations = getattr(self.module_planning, 'conversations', None)
            if conversations is None:
                raise AppError('MODULE_PLAN_NOT_APPLIED', '规划版本不可用', 409)
            await conversations.validate_applied_version(project_id, request.module_plan_id,
                request.planning_applied_version_id, 'suite')
        master_snapshot = None
        if request.module_plan_id:
            if self.module_planning is None:
                raise AppError("MODULE_PLANNER_UNAVAILABLE", "自动规划服务不可用", 503)
            master_snapshot = await self.module_planning.snapshot(project_id, request.module_plan_id, "suite")
        if master_snapshot and (master_snapshot.get("planningContractVersion") == "regular-design-v1") != (request.creation_mode == "regular"):
            raise AppError("MODULE_PLAN_MODE_MISMATCH", "规划模式不匹配，请重新规划", 409)
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
        project = await self.project_repository.get_project(project_id, workspace_id)
        if project is None or project.status != "active":
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        reverse_overview = None
        if request.reverse_version_id is not None:
            if self.reverse_projects is None:
                raise AppError("REVERSE_PLANNING_UNAVAILABLE", "反推规划服务不可用", 503)
            reverse_overview = await self.reverse_projects.planning_context(request.reverse_version_id)

        source_records: list[tuple[Any, Any, Any]] = []
        for source_asset_id in request.source_asset_ids:
            # 原图、白底图和生成结果都可以作为套图规划输入，只校验归属与可用状态。
            asset = await self.project_repository.get_asset(source_asset_id, workspace_id)
            if (
                asset is None
                or asset.project_id != project_id
                or asset.state != "available"
            ):
                raise AppError("INVALID_SOURCE_ASSET", "源图不属于当前项目或不可用", 400)
            source_object = await self.project_repository.get_object(asset.object_id, workspace_id)
            if source_object is None or source_object.state != "available":
                raise AppError("INVALID_SOURCE_ASSET", "源图对象不可用", 400)
            stored = await self.project_storage.get(source_object.storage_key)
            if stored is None or stored.content_type != source_object.media_type:
                raise AppError("INVALID_SOURCE_ASSET", "源图对象元数据不一致", 409)
            source_records.append((asset, source_object, stored))

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
        style = _find_style(config.get("styleCategories"), request.style_id)
        seed = (await resolve_marketplace_style_seed(style, self.prompt_repository))
        custom_style = normalize_custom_style(request.custom_style)
        cards = await resolve_constraint_cards(
            config,
            market_id=request.market_id,
            style_id=request.style_id,
            prompt_repository=self.prompt_repository,
            style_seed=seed.text,
        )
        references = await self.reference_resolver.resolve(workspace_id, request.references)

        bound = await self.prompt_models.bind(config, self.planner_compiler) if self.prompt_models and request.creation_mode != "regular" else None
        planner_compiler = bound.compiler if bound else self.planner_compiler
        prompt_connection = bound.snapshot if bound else None
        module_inputs: list[RepositoryModuleInput] = []
        module_context: list[
            tuple[
                SuitePlanModuleInput,
                dict[str, Any],
                list[dict[str, str]],
                Any,
                str,
                str,
                list[bytes],
                list[str],
            ]
        ] = []
        for selected in request.modules:
            module = _find_item(runtime_module_catalog(config, "suite"), selected.module_id, "详情页模块")
            if module.get("mode") != "suite":
                raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页模块选择无效", 400)
            parameters = _normalize_parameters(selected.module_parameters)
            if request.creation_mode == "regular":
                module_snapshot = regular_snapshot(request, selected, master_snapshot, module, parameters, market, style, cards)
                module_inputs.append(RepositoryModuleInput(selected.task_id or selected.module_id, len(module_inputs)+1, selected.result_count, module_snapshot["title"], parameters, module_snapshot))
                module_context.append((selected, module, parameters, references, "", module_snapshot["compiledTaskPrompt"], [], []))
                continue
            task_outline = task_outline_from_master(
                master_snapshot, selected.task_id or selected.module_id, selected.module_id
            )
            reverse_reference = selected.reverse_reference
            if reverse_reference is None and task_outline and task_outline.get("referenceModuleId"):
                reverse_reference = {
                    "versionId": request.reverse_version_id,
                    "moduleId": task_outline["referenceModuleId"],
                }
            reverse_snapshot = None
            reverse_prompt_context = None
            reverse_images: list[bytes] = []
            reverse_mimes: list[str] = []
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
            module_prompt = await resolve_module_prompt(
                config, mode="suite", module_id=selected.module_id,
                prompt_repository=self.prompt_repository,
            )
            system_prompt, user_prompt, prompt_snapshot = build_v2_compiler_prompts(
                task_design=selected.task_design,
                seed=seed, module=module, module_parameters=parameters,
                module_prompt=module_prompt,
                custom_style=custom_style,
                task_outline=task_outline,
                shared_visual_direction=(master_snapshot or {}).get("sharedVisualDirection", ""),
                placement="detail",
                market={"id": market.get("id"), "label": market.get("label")},
                output={"aspectRatio": request.aspect_ratio, "resolution": request.resolution, "language": request.output_language},
                constraints={"productAuthenticity": cards.authenticity.content, "market": cards.market.content},
                additional_context={
                    "currentTaskId": selected.task_id or selected.module_id,
                    "tasks": [{"taskId": item.task_id or item.module_id, "moduleId": item.module_id, "moduleParameters": _normalize_parameters(item.module_parameters)} for item in request.modules],
                    "planningMaster": master_snapshot,
                    "userNotes": request.user_notes.strip(),
                    "references": [reference.to_snapshot() for reference in references],
                    **(
                        {"additionalContext": {
                            **({"reversePlanning": reverse_overview} if reverse_overview else {}),
                            **({"reverseReference": reverse_prompt_context} if reverse_prompt_context else {}),
                        }}
                        if reverse_overview or reverse_prompt_context else {}
                    ),
                },
            )
            prompt_snapshot = {**prompt_snapshot, "source": "server_module_planner_v2"}
            module_snapshot = {
                "taskId": selected.task_id or selected.module_id,
                "moduleId": selected.module_id,
                **({"promptModelConnection": prompt_connection} if prompt_connection else {}),
                "module": module,
                "moduleParameters": parameters,
                "prompt": prompt_snapshot,
                **prompt_snapshot,
                "constraints": cards.to_snapshot(),
                "plannerVersion": PLANNER_VERSION_V2,
                **({"reverseReference": reverse_snapshot} if reverse_snapshot else {}),
                **({"styleSeed": seed.to_snapshot(), "selection": {
                    "module": module, "moduleParameters": parameters,
                    "customStyle": custom_style, "outputLanguage": request.output_language,
                    "aspectRatio": request.aspect_ratio, "resolution": request.resolution,
                }}),
            }
            module_inputs.append(
                RepositoryModuleInput(
                    selected.task_id or selected.module_id,
                    selected.position if hasattr(selected, "position") else len(module_inputs) + 1,
                    selected.result_count,
                    (prompt_snapshot["effectiveTaskOutline"] or {}).get("taskTitle") or module.get("label", selected.module_id),
                    parameters,
                    module_snapshot,
                )
            )
            module_context.append(
                (
                    selected,
                    module,
                    parameters,
                    references,
                    system_prompt,
                    user_prompt,
                    reverse_images,
                    reverse_mimes,
                )
            )

        source_snapshot = [
            {
                "assetId": str(asset.id),
                "objectId": str(source_object.id),
                "filename": source_object.original_filename,
                "mediaType": source_object.media_type,
                "byteSize": source_object.byte_size,
                "width": source_object.width,
                "height": source_object.height,
                "sha256": source_object.sha256,
            }
            for asset, source_object, _stored in source_records
        ]
        snapshot = {
            "creationMode":request.creation_mode,
            **({'planningAppliedVersionId': str(request.planning_applied_version_id)} if request.planning_applied_version_id else {}),
            **({"recipe":dict(RECIPE)} if request.creation_mode == "regular" else {}),
            "runtimeModules": runtime_catalog_snapshot(config),
            "plannerVersion": "regular-design-v1" if request.creation_mode == "regular" else PLANNER_VERSION_V2,
            **({"designKnowledge": design_knowledge_context(load_design_knowledge())} if request.creation_mode != "regular" else {}),
            "styleSeed": seed.to_snapshot(),
            **({"planningMaster": master_snapshot} if master_snapshot else {}),
            **({"reversePlanning": reverse_overview} if reverse_overview else {}),
            **({"promptModelConnection": prompt_connection} if prompt_connection else {}),
            "sourceAssets": source_snapshot,
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
                "aspectRatio": request.aspect_ratio,
                "resolution": request.resolution,
                "outputLanguage": request.output_language,
                "customStyle": request.custom_style.strip(),
                "userNotes": request.user_notes.strip(),
            },
            "constraints": cards.to_snapshot(),
            "references": [reference.to_snapshot() for reference in references],
        }
        plan, duplicate = await self.plan_repository.create_compiling(
            workspace_id,
            project_id,
            idempotency_key,
            fingerprint,
            snapshot,
            module_inputs,
        )
        if duplicate:
            return plan

        compilations: dict[str, SuitePlanModuleCompilation] = {}
        try:
            for (
                selected,
                module,
                parameters,
                _references,
                system_prompt,
                user_prompt,
                reverse_images,
                reverse_mimes,
            ) in module_context:
                module_input = next(item for item in module_inputs if item.module_key == (selected.task_id or selected.module_id))
                if request.creation_mode == "regular":
                    rendered = module_input.prompt_snapshot.get("compiledTaskPrompt", "")
                    compilations[selected.task_id or selected.module_id] = SuitePlanModuleCompilation(
                        copy_summary=(selected.regular_task or {}).get("copy", ""),
                        visual_direction=(selected.regular_task or {}).get("goal", ""),
                        task_prompt=rendered,
                        compiler_output={"creationMode": "regular", "recipe": "local-regular-adapted-v1"},
                    )
                    await self.plan_repository.save_planning_snapshot(
                        plan.id, workspace_id, snapshot, {item.module_key: item.prompt_snapshot for item in module_inputs},
                    )
                    continue
                result = await planner_compiler.compile(
                    SuitePlanCompilerRequest(
                        module_id=selected.module_id,
                        module=module,
                        module_parameters=parameters,
                        image_inputs=[
                            *[stored.data for _asset, _object, stored in source_records],
                            *reverse_images,
                        ],
                        image_mime_types=[
                            *[obj.media_type for _asset, obj, _stored in source_records],
                            *reverse_mimes,
                        ],
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        planner_version=PLANNER_VERSION_V2,
                    )
                )
                result = parse_v2_result(result, error_code="PLANNING_COMPILER_INVALID_RESPONSE")
                rendered = render_v2_module_prompt(result)
                module_input.prompt_snapshot["modulePlanning"] = freeze_v2_module_planning(result, rendered)
                await self.plan_repository.save_planning_snapshot(
                    plan.id, workspace_id, snapshot, {item.module_key: item.prompt_snapshot for item in module_inputs},
                )
                compilations[selected.task_id or selected.module_id] = SuitePlanModuleCompilation(
                    copy_summary=result.copySummary, visual_direction=result.visualDirection,
                    task_prompt=rendered,
                    compiler_output=result.model_dump(),
                )
        except AppError as exc:
            await self.plan_repository.mark_failed(plan.id, workspace_id, exc.code, exc.message)
            raise
        except Exception:
            await self.plan_repository.mark_failed(
                plan.id, workspace_id, "PLANNING_COMPILER_FAILED", "详情页规划编译服务请求失败"
            )
            raise AppError("PLANNING_COMPILER_FAILED", "详情页规划编译服务请求失败", 502) from None
        return await self.plan_repository.mark_awaiting_confirmation(
            plan.id, workspace_id, compilations
        )

    async def update_module(
        self,
        project_id: UUID,
        plan_id: UUID,
        request: SuitePlanModuleUpdateInput,
    ):
        await self.get_plan(project_id, plan_id)
        raise AppError("V2_PROMPT_READ_ONLY", "统一规划结果不可直接修改，请调整模块参数后重新编译", 409)

    async def get_plan(self, project_id: UUID, plan_id: UUID):
        workspace_id = self.identity_provider.get_context().workspace_id
        detail = await self.plan_repository.get_plan_detail(
            plan_id, workspace_id, project_id
        )
        if detail is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "详情页规划不存在", 404)
        return detail

    async def get_latest_plan(self, project_id: UUID):
        workspace_id = self.identity_provider.get_context().workspace_id
        detail = await self.plan_repository.get_latest(project_id, workspace_id)
        if detail is None:
            raise AppError("SUITE_PLAN_NOT_FOUND", "当前项目还没有详情页规划", 404)
        return detail

    async def reorder_modules(
        self,
        project_id: UUID,
        plan_id: UUID,
        ordered_module_ids: list[UUID],
        *,
        expected_plan_revision: int,
    ):
        workspace_id = self.identity_provider.get_context().workspace_id
        return await self.plan_repository.reorder_modules(
            plan_id,
            workspace_id,
            project_id,
            expected_plan_revision=expected_plan_revision,
            ordered_module_ids=ordered_module_ids,
        )

    @staticmethod
    def _validate_request(request: SuitePlanCompilationInput) -> None:
        if any(item.task_id is not None and (item.task_id != item.task_id.strip() or len(item.task_id) > 100) for item in request.modules):
            raise AppError("SUITE_PLAN_INVALID_INPUT", "任务标识无效", 400)
        if not 1 <= len(request.source_asset_ids) <= 4:
            raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页规划需要选择 1 到 4 张源图", 400)
        if len(set(request.source_asset_ids)) != len(request.source_asset_ids):
            raise AppError("SUITE_PLAN_INVALID_INPUT", "源图不能重复选择", 400)
        if not request.modules:
            raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页规划必须至少选择一个模块", 400)
        module_ids = [(item.task_id if item.task_id is not None else item.module_id).strip() for item in request.modules]
        if any(not module_id or len(module_id) > 100 for module_id in module_ids) or len(module_ids) != len(set(module_ids)) or any(not item.module_id.strip() for item in request.modules):
            raise AppError("SUITE_PLAN_INVALID_INPUT", "详情页模块不能重复或为空", 400)
        if any(item.result_count not in {1, 2, 3, 4} for item in request.modules):
            raise AppError("SUITE_PLAN_INVALID_INPUT", "模块生成数量必须为 1 到 4", 400)
        if not request.aspect_ratio.strip() or not request.resolution.strip():
            raise AppError("SUITE_PLAN_INVALID_INPUT", "图片比例和分辨率不能为空", 400)
        if len(request.user_notes) > 4000 or len(request.custom_style) > 500:
            raise AppError("SUITE_PLAN_INVALID_INPUT", "补充说明长度超出限制", 400)
