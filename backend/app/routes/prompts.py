from uuid import UUID
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from ..core.errors import AppError
from ..core.http import success_response
from ..prompt_repository import PromptRepositoryError
from ..prompt_service import DuplicatePromptVersion


prompt_router = APIRouter()


# Use Pydantic models to properly handle JSON body parsing
class PromptTemplateCreate(BaseModel):
    code: str
    name: str
    kind: str
    kindName: str | None = None
    executionTarget: str = "llm"
    body: str
    userPromptTemplate: str = ""
    inputSchema: list[Any] = Field(default_factory=list)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    applicability: dict[str, Any] = Field(default_factory=dict)
    generationParams: dict[str, Any] = Field(default_factory=dict)
    changeNote: str | None = None
    categoryId: UUID | None = None
    stage: str = "plan"


class PromptVersionCreate(BaseModel):
    baseVersionId: str
    body: str
    userPromptTemplate: str = ""
    generationParams: dict[str, Any] = Field(default_factory=dict)
    changeNote: str | None = None
    inputSchema: list[Any] | None = None
    outputSchema: dict[str, Any] | None = None
    applicability: dict[str, Any] | None = None


class PromptTemplateBatchDelete(BaseModel):
    templateIds: list[str]


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    kindName: str | None = None
    categoryId: UUID | None = None


class PromptCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class PromptCategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def _version_view(version) -> dict:
    return {
        "id": str(version.id),
        "templateId": str(version.template_id),
        "templateVersionId": str(version.id),
        "versionNo": version.version_no,
        "name": version.name,
        "kind": version.kind,
        "executionTarget": version.execution_target,
        "body": version.body,
        "userPromptTemplate": version.user_prompt_template,
        "inputSchema": version.input_schema,
        "outputSchema": version.output_schema,
        "applicability": version.applicability,
        "generationParams": version.generation_params,
        "contentSha256": version.content_sha256,
        "source": version.source,
        "changeNote": version.change_note,
        "createdBy": version.created_by,
        # 当前提示词版本直接存储在数据库，旧版 Markdown 文件同步字段已从
        # SQLAlchemy 模型移除。为兼容旧客户端保留响应键，但不再提供旧元数据。
        "filePath": getattr(version, "file_path", None),
        "fileSyncStatus": getattr(version, "file_sync_status", None),
        "fileSyncError": getattr(version, "file_sync_error", None),
        "createdAt": version.created_at.isoformat(),
        "syncedAt": version.synced_at.isoformat() if getattr(version, "synced_at", None) else None,
    }


def _template_data(template, versions, category, include_versions: bool = False) -> dict:
    default = next((item for item in versions if item.id == template.default_version_id), None)
    data = {
        "id": str(template.id),
        "code": template.code,
        "name": template.name,
        "kind": template.kind,
        "kindName": template.kind_name,
        "stage": getattr(template, "stage", "plan"),
        "executionTarget": template.execution_target,
        "defaultVersionId": str(template.default_version_id) if template.default_version_id else None,
        "defaultVersion": _version_view(default) if default else None,
        "versionCount": len(versions),
        "createdAt": template.created_at.isoformat(),
        "updatedAt": template.updated_at.isoformat(),
        "templateId": str(template.id),
        "templateVersionId": str(default.id) if default else "",
        "versionNo": default.version_no if default else 0,
        "inputSchema": default.input_schema if default else [],
        "applicability": default.applicability if default else {},
        "categoryId": str(template.category_id) if template.category_id else None,
        "categoryName": category.name if category else None,
    }
    if include_versions:
        data["versions"] = [_version_view(item) for item in versions]
    return data


async def _template_view(request: Request, template, include_versions: bool = False) -> dict:
    service = request.app.state.prompt_service
    versions = await service.list_versions(template.id)
    category = await service.repository.get_category(template.category_id) if template.category_id else None
    return _template_data(template, versions, category, include_versions)


def _category_view(category) -> dict:
    return {
        "id": str(category.id),
        "name": category.name,
        "sortOrder": category.sort_order,
        "createdAt": category.created_at.isoformat(),
        "updatedAt": category.updated_at.isoformat(),
    }


@prompt_router.get("/api/prompt-categories")
async def list_prompt_categories(request: Request):
    service = request.app.state.prompt_service
    categories = await service.list_categories()
    counts = {category.id: await service.repository.count_templates_for_category(category.id) for category in categories}
    return success_response([{**_category_view(category), "templateCount": counts[category.id]} for category in categories])


@prompt_router.post("/api/prompt-categories", status_code=201)
async def create_prompt_category(payload: PromptCategoryCreate, request: Request):
    service = request.app.state.prompt_service
    try:
        category = await service.create_category(payload.name)
        return success_response(_category_view(category))
    except PromptRepositoryError as exc:
        code = str(exc)
        raise AppError(code, "prompt category is invalid or already exists", 409 if code == "PROMPT_CATEGORY_CONFLICT" else 400) from exc


@prompt_router.patch("/api/prompt-categories/{category_id}")
async def update_prompt_category(category_id: UUID, payload: PromptCategoryUpdate, request: Request):
    service = request.app.state.prompt_service
    try:
        category = await service.update_category(category_id, payload.name)
        return success_response(_category_view(category))
    except PromptRepositoryError as exc:
        code = str(exc)
        status = 404 if code == "PROMPT_CATEGORY_NOT_FOUND" else 409 if code == "PROMPT_CATEGORY_CONFLICT" else 400
        raise AppError(code, "prompt category update failed", status) from exc


@prompt_router.delete("/api/prompt-categories/{category_id}")
async def delete_prompt_category(category_id: UUID, request: Request):
    service = request.app.state.prompt_service
    try:
        affected = await service.delete_category(category_id)
        return success_response({"id": str(category_id), "affectedTemplateCount": affected})
    except PromptRepositoryError as exc:
        raise AppError(str(exc), "prompt category does not exist", 404) from exc


@prompt_router.get("/api/prompt-templates")
async def list_prompt_templates(request: Request, stage: str | None = None):
    service = request.app.state.prompt_service
    templates = await service.list_templates(stage)
    if not templates:
        return success_response([])
    versions_by_template = {item.id: [] for item in templates}
    for version in await service.list_versions_for_templates(list(versions_by_template)):
        versions_by_template[version.template_id].append(version)
    categories = {item.id: item for item in await service.list_categories()}
    return success_response([
        _template_data(item, versions_by_template[item.id], categories.get(item.category_id))
        for item in templates
    ])


@prompt_router.post("/api/prompt-templates", status_code=201)
async def create_prompt_template(payload: PromptTemplateCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    service = request.app.state.prompt_service
    try:
        result = await service.create_template({
            "code": payload.code,
            "name": payload.name,
            "kind": payload.kind,
            "kind_name": payload.kindName or {
                "planner": "文生文",
                "direct_generation": "文生文",
                "image_to_image": "图生图",
                "image_to_text": "图生文",
                "text_to_image": "文生图",
                "text_to_text": "文生文",
            }.get(payload.kind, payload.kind),
            "execution_target": payload.executionTarget,
            "body": payload.body,
            "user_prompt_template": payload.userPromptTemplate,
            "input_schema": payload.inputSchema,
            "output_schema": payload.outputSchema,
            "applicability": payload.applicability,
            "generation_params": payload.generationParams,
            "change_note": payload.changeNote,
            "category_id": payload.categoryId,
            "stage": payload.stage,
        }, idempotency_key=idempotency_key)
        return success_response({"template": await _template_view(request, result.template), "version": _version_view(result.version)})
    except KeyError as exc:
        raise AppError("INVALID_PROMPT", f"missing field: {exc.args[0]}", 400) from exc
    except PromptRepositoryError as exc:
        code = str(exc)
        raise AppError(code, "prompt template conflict", 409 if code == "PROMPT_CODE_CONFLICT" else 400) from exc


@prompt_router.get("/api/prompt-templates/{template_id}")
async def get_prompt_template(template_id: UUID, request: Request):
    service = request.app.state.prompt_service
    template = await service.repository.get_template(template_id)
    if not template:
        raise AppError("PROMPT_TEMPLATE_NOT_FOUND", "prompt template does not exist", 404)
    return success_response(await _template_view(request, template, include_versions=True))


@prompt_router.get("/api/prompt-templates/{template_id}/versions")
async def list_prompt_versions(template_id: UUID, request: Request):
    service = request.app.state.prompt_service
    if not await service.repository.get_template(template_id):
        raise AppError("PROMPT_TEMPLATE_NOT_FOUND", "prompt template does not exist", 404)
    return success_response([_version_view(item) for item in await service.list_versions(template_id)])


@prompt_router.get("/api/prompt-versions/{version_id}")
async def get_prompt_version(version_id: UUID, request: Request):
    service = request.app.state.prompt_service
    version = await service.repository.get_version(version_id)
    if not version:
        raise AppError("PROMPT_VERSION_NOT_FOUND", "prompt version does not exist", 404)
    return success_response(_version_view(version))


@prompt_router.get("/api/prompt-templates/{template_id}/resolve")
async def resolve_prompt_version(template_id: UUID, request: Request, versionId: UUID | None = None):
    service = request.app.state.prompt_service
    try:
        version = await service.resolve_version(template_id, versionId)
        return success_response(_version_view(version))
    except PromptRepositoryError as exc:
        code = str(exc)
        raise AppError(code, "prompt version cannot be resolved", 409 if code == "PROMPT_VERSION_OWNERSHIP" else 404) from exc


@prompt_router.post("/api/prompt-templates/{template_id}/versions", status_code=201)
async def create_prompt_version(template_id: UUID, payload: PromptVersionCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    service = request.app.state.prompt_service
    try:
        result = await service.create_version(template_id, UUID(payload.baseVersionId), {
            "body": payload.body,
            "user_prompt_template": payload.userPromptTemplate,
            "generation_params": payload.generationParams,
            "change_note": payload.changeNote,
            **({"input_schema": payload.inputSchema} if payload.inputSchema is not None else {}),
            **({"output_schema": payload.outputSchema} if payload.outputSchema is not None else {}),
            **({"applicability": payload.applicability} if payload.applicability is not None else {}),
        }, idempotency_key=idempotency_key)
        return success_response({"template": await _template_view(request, result.template), "version": _version_view(result.version)})
    except ValueError as exc:
        if isinstance(exc, DuplicatePromptVersion):
            raise AppError("PROMPT_VERSION_DUPLICATE", "prompt content is unchanged", 409) from exc
        raise AppError("INVALID_PROMPT", "invalid prompt version request", 400) from exc
    except PromptRepositoryError as exc:
        code = str(exc)
        raise AppError(code, "prompt version request failed", 404 if code.endswith("NOT_FOUND") else 409) from exc


@prompt_router.post("/api/prompt-versions/{version_id}/sync-retry")
async def retry_prompt_sync(version_id: UUID, request: Request):
    service = request.app.state.prompt_service
    try:
        version = await service.retry_sync(version_id)
        return success_response(_version_view(version))
    except PromptRepositoryError as exc:
        raise AppError(str(exc), "prompt version does not exist", 404) from exc


@prompt_router.delete("/api/prompt-templates/{template_id}")
async def delete_prompt_template(template_id: UUID, request: Request):
    service = request.app.state.prompt_service
    success = await service.delete_template(template_id)
    if not success:
        raise AppError("PROMPT_TEMPLATE_NOT_FOUND", "prompt template does not exist", 404)
    return success_response({"id": str(template_id)})


@prompt_router.patch("/api/prompt-templates/{template_id}")
async def update_prompt_template(template_id: UUID, payload: PromptTemplateUpdate, request: Request):
    service = request.app.state.prompt_service
    update_data = {}
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.kindName is not None:
        update_data["kindName"] = payload.kindName
    if "categoryId" in payload.model_fields_set:
        update_data["categoryId"] = payload.categoryId

    if not update_data:
        raise AppError("NO_UPDATE_DATA", "No fields to update", 400)

    template = await service.update_template(template_id, update_data)
    if not template:
        raise AppError("PROMPT_TEMPLATE_NOT_FOUND", "prompt template does not exist", 404)

    return success_response(await _template_view(request, template))


@prompt_router.post("/api/prompt-templates/{template_id}/versions/{version_id}/set-default")
async def set_default_version(template_id: UUID, version_id: UUID, request: Request):
    service = request.app.state.prompt_service
    template = await service.set_default_version(template_id, version_id)
    if not template:
        raise AppError("PROMPT_VERSION_NOT_FOUND", "version does not exist or does not belong to this template", 404)

    return success_response(await _template_view(request, template))


@prompt_router.post("/api/prompt-templates/batch-delete")
async def batch_delete_prompt_templates(payload: PromptTemplateBatchDelete, request: Request):
    service = request.app.state.prompt_service
    template_ids = [UUID(tid) for tid in payload.templateIds]
    deleted_ids = await service.delete_templates(template_ids)
    return success_response({"deletedIds": [str(tid) for tid in deleted_ids]})
