import json
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from ..project_storage import inspect_project_image
from ..reverse_project_repository import ReverseReferenceRecord
from ..storage import StoredObject
from .module_planning_service import ModuleMasterRequest
from .reverse_image_analysis import observe_reference_image, observed_layout


class ReverseOverall(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contentFlow: str = Field(min_length=1, max_length=10000)
    visualSystem: str = Field(min_length=1, max_length=10000)
    moduleStrategy: str = Field(min_length=1, max_length=10000)
    adaptationRules: str = Field(min_length=1, max_length=10000)


class ReverseModule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    referenceImageId: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=5000)
    layout: str = Field(min_length=1, max_length=5000)
    informationHierarchy: str = Field(min_length=1, max_length=5000)
    typography: str = Field(min_length=1, max_length=5000)
    colorAndLighting: str = Field(min_length=1, max_length=5000)
    adaptationNotes: str = Field(min_length=1, max_length=5000)


class ReverseAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=10000)
    suitableFor: str = Field(min_length=1, max_length=10000)
    goal: str = Field(min_length=1, max_length=10000)
    requiredMaterials: str = Field(min_length=1, max_length=10000)
    notSuitableFor: str = Field(min_length=1, max_length=10000)
    overall: ReverseOverall
    modules: list[ReverseModule] = Field(min_length=1, max_length=64)


def reverse_project_object_key(
    workspace_id: UUID, project_id: UUID, reference_id: UUID, mime_type: str
) -> str:
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime_type]
    return f"reverse-projects/{workspace_id}/{project_id}/{reference_id}/original.{extension}"


class ReverseProjectService:
    def __init__(
        self,
        repository: Any,
        identity_provider: IdentityProvider,
        *,
        storage: Any | None = None,
        max_upload_bytes: int = 12 * 1024 * 1024,
        project_repository: Any | None = None,
        generation_config_service: Any | None = None,
        planner: Any | None = None,
        prompt_models: Any | None = None,
    ) -> None:
        self.repository = repository
        self.identity_provider = identity_provider
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes
        self.project_repository = project_repository
        self.generation_config_service = generation_config_service
        self.planner = planner
        self.prompt_models = prompt_models

    @property
    def workspace_id(self) -> UUID:
        return self.identity_provider.get_context().workspace_id

    async def create_project(self, name: str, category: str = ""):
        normalized_name = name.strip() if isinstance(name, str) else ""
        if not normalized_name:
            raise AppError("REVERSE_PROJECT_NAME_REQUIRED", "反推项目名称不能为空", 400)
        return await self.repository.create_project(
            self.workspace_id, normalized_name, category.strip()
        )

    async def list_projects(self):
        return await self.repository.list_projects(self.workspace_id)

    async def get_project(self, project_id: UUID):
        project = await self.repository.get_project(self.workspace_id, project_id)
        if project is None:
            raise AppError("REVERSE_PROJECT_NOT_FOUND", "反推项目不存在", 404)
        return project

    async def update_project(
        self, project_id: UUID, expected_revision: int, changes: dict[str, Any]
    ):
        names = {
            "name": "name",
            "category": "category",
            "summary": "summary",
            "suitableFor": "suitable_for",
            "goal": "goal",
            "requiredMaterials": "required_materials",
            "notSuitableFor": "not_suitable_for",
            "overall": "overall",
            "modules": "modules",
        }
        normalized = {names[key]: deepcopy(value) for key, value in changes.items() if key in names}
        if "name" in normalized and not str(normalized["name"]).strip():
            raise AppError("REVERSE_PROJECT_NAME_REQUIRED", "反推项目名称不能为空", 400)
        return await self.repository.update_project(
            self.workspace_id, project_id, expected_revision, normalized
        )

    async def add_reference(
        self, project_id: UUID, filename: str, declared_mime: str | None, body: bytes
    ):
        if self.storage is None:
            raise AppError("REVERSE_STORAGE_UNAVAILABLE", "参考图存储不可用", 503)
        project = await self.get_project(project_id)
        if len(project.references) >= 16:
            raise AppError("REVERSE_REFERENCE_LIMIT", "每个反推项目最多上传 16 张参考图", 400)
        mime, width, height, sha256 = inspect_project_image(
            body, declared_mime, self.max_upload_bytes
        )
        reference_id = uuid4()
        storage_key = reverse_project_object_key(
            self.workspace_id, project_id, reference_id, mime
        )
        await self.storage.put(StoredObject(storage_key, body, mime))
        reference = ReverseReferenceRecord(
            reference_id,
            self.workspace_id,
            project_id,
            len(project.references) + 1,
            filename or "reference",
            width,
            height,
            mime,
            storage_key,
            sha256,
        )
        try:
            return await self.repository.add_reference(
                self.workspace_id, project_id, reference
            )
        except Exception:
            await self.storage.delete(storage_key)
            raise

    async def remove_reference(self, project_id: UUID, reference_id: UUID):
        return await self.repository.remove_reference(
            self.workspace_id, project_id, reference_id
        )

    async def reorder_references(
        self, project_id: UUID, expected_revision: int, reference_ids: list[UUID]
    ):
        return await self.repository.reorder_references(
            self.workspace_id, project_id, expected_revision, reference_ids
        )

    async def preview_reference(self, project_id: UUID, reference_id: UUID) -> StoredObject:
        reference = await self.repository.get_reference(
            self.workspace_id, project_id, reference_id
        )
        if reference is None or self.storage is None:
            raise AppError("REVERSE_REFERENCE_NOT_FOUND", "参考图不存在", 404)
        stored = await self.storage.get(reference.storage_key)
        if stored is None or stored.content_type != reference.mime_type:
            raise AppError("REVERSE_REFERENCE_NOT_FOUND", "参考图对象不存在", 404)
        return stored

    async def analyze(self, project_id: UUID, expected_revision: int):
        project = await self.repository.claim_analysis(
            self.workspace_id, project_id, expected_revision
        )
        try:
            if not project.references:
                raise AppError("REVERSE_ANALYSIS_REQUIRES_REFERENCES", "请先上传参考图", 400)
            if self.storage is None or self.planner is None:
                raise AppError("MODULE_PLANNER_UNAVAILABLE", "规划大师服务未配置", 503)
            images: list[bytes] = []
            mimes: list[str] = []
            image_roles: list[dict[str, Any]] = []
            for index, reference in enumerate(project.references, 1):
                stored = await self.storage.get(reference.storage_key)
                if stored is None or stored.content_type != reference.mime_type:
                    raise AppError("REVERSE_REFERENCE_NOT_FOUND", "参考图对象不存在", 400)
                images.append(stored.data)
                mimes.append(stored.content_type)
                image_roles.append(
                    {
                        "imageIndex": index,
                        "referenceImageId": str(reference.id),
                    }
                )
            planner = self.planner
            if self.prompt_models is not None and self.generation_config_service is not None:
                published = await self.generation_config_service.get_published()
                bound = await self.prompt_models.bind(published.content, planner)
                planner = bound.compiler
            system_prompt = (
                "你是电商视觉拆解专家。分析整套参考图的内容顺序、视觉系统、模块策略和适配规则。"
                "本阶段分析整套内容职责、信息层级、文字与光影；每张参考图必须恰好对应一个模块，"
                "referenceImageId使用对应图像标识，不能漏图或让多个模块重复引用同一张图。"
                "layout只描述场景构图概览，具体产品机位和朝向由后续逐图观察记录决定，不编造相机角度。"
                "只总结设计方法，不得把参考商品的参数、价格、功效或认证当作当前商品事实。"
                "严格返回 outputSchema 对应的 JSON。"
            )
            user_prompt = json.dumps(
                {
                    "analysisStage": "overall_strategy",
                    "project": {"name": project.name, "category": project.category},
                    "imageRoles": image_roles,
                    "outputSchema": ReverseAnalysisOutput.model_json_schema(),
                },
                ensure_ascii=False,
            )
            raw = await planner.plan_modules(
                ModuleMasterRequest(system_prompt, user_prompt, images, mimes)
            )
            parsed = ReverseAnalysisOutput.model_validate(raw).model_dump()
            reference_ids = {str(item.id) for item in project.references}
            module_ids = [item["id"] for item in parsed["modules"]]
            if len(module_ids) != len(set(module_ids)) or any(
                item["referenceImageId"] not in reference_ids for item in parsed["modules"]
            ):
                raise AppError("REVERSE_ANALYSIS_INVALID_RESPONSE", "反推分析返回了无效模块引用", 502)
            module_reference_ids = [item["referenceImageId"] for item in parsed["modules"]]
            if len(module_reference_ids) != len(reference_ids) or set(module_reference_ids) != reference_ids:
                raise AppError("REVERSE_ANALYSIS_INVALID_RESPONSE", "反推分析必须逐张对应全部参考图", 502)
            modules_by_reference = {item["referenceImageId"]: item for item in parsed["modules"]}
            # Global strategy is separate from geometry. Each observation sees
            # exactly one image and is the source of truth for that module's pose.
            ordered_modules = []
            for reference, image, mime in zip(project.references, images, mimes):
                observation = await observe_reference_image(planner, str(reference.id), image, mime)
                module = modules_by_reference[str(reference.id)]
                module["layout"] = observed_layout(observation)
                module["adaptationNotes"] = observation.adaptationNotes
                # The rendered observation must also fit the existing public contract.
                ordered_modules.append(ReverseModule.model_validate(module).model_dump())
            parsed["modules"] = ordered_modules
            result = {
                "category": parsed["category"],
                "summary": parsed["summary"],
                "suitable_for": parsed["suitableFor"],
                "goal": parsed["goal"],
                "required_materials": parsed["requiredMaterials"],
                "not_suitable_for": parsed["notSuitableFor"],
                "overall": parsed["overall"],
                "modules": parsed["modules"],
            }
            return await self.repository.complete_analysis(
                self.workspace_id, project_id, expected_revision, result
            )
        except Exception as exc:
            error = exc if isinstance(exc, AppError) else AppError(
                "REVERSE_ANALYSIS_INVALID_RESPONSE"
                if isinstance(exc, ValidationError)
                else "REVERSE_ANALYSIS_FAILED",
                "反推分析返回格式无效" if isinstance(exc, ValidationError) else "反推分析失败",
                502,
            )
            await self.repository.fail_analysis(
                self.workspace_id, project_id, error.message
            )
            raise error from None

    async def publish(self, project_id: UUID, expected_revision: int):
        project = await self.get_project(project_id)
        if project.revision != expected_revision:
            raise AppError("REVERSE_PROJECT_REVISION_CONFLICT", "反推草稿已被更新，请重新加载", 409)
        document = self._document(project)
        self._validate_publishable(document)
        return await self.repository.publish(
            self.workspace_id, project_id, expected_revision, document
        )

    async def get_project_version(self, project_id: UUID, version_id: UUID):
        version = await self.get_version(version_id)
        if version.reverse_project_id != project_id:
            raise AppError("REVERSE_VERSION_NOT_FOUND", "反推版本不存在", 404)
        return version

    async def get_version(self, version_id: UUID):
        version = await self.repository.get_version(self.workspace_id, version_id)
        if version is None:
            raise AppError("REVERSE_VERSION_NOT_FOUND", "反推版本不存在", 404)
        return version

    async def planning_context(self, version_id: UUID, module_id: str | None = None):
        version = await self.get_version(version_id)
        document = version.document
        modules = deepcopy(document["modules"])
        if module_id is None:
            modules = [
                {"id": item["id"], "title": item["title"], "goal": item["goal"]}
                for item in modules
            ]
        else:
            modules = [item for item in modules if item["id"] == module_id]
            if not modules:
                raise AppError("REVERSE_MODULE_NOT_FOUND", "反推模块不存在", 404)
        return {
            "versionId": str(version.id),
            "reverseProjectId": str(version.reverse_project_id),
            "versionNo": version.version_no,
            "name": document["name"],
            "introduction": {
                "category": document["category"],
                "summary": document["summary"],
                "suitableFor": document["suitableFor"],
                "goal": document["goal"],
                "requiredMaterials": document["requiredMaterials"],
                "notSuitableFor": document["notSuitableFor"],
            },
            "overall": deepcopy(document["overall"]),
            "modules": modules,
        }

    async def planning_images(
        self, version_id: UUID, module_id: str | None = None
    ) -> tuple[list[bytes], list[str]]:
        if module_id is None:
            return [], []
        version = await self.get_version(version_id)
        module = next(
            (item for item in version.document["modules"] if item["id"] == module_id), None
        )
        if module is None:
            raise AppError("REVERSE_MODULE_NOT_FOUND", "反推模块不存在", 404)
        reference = next(
            (
                item
                for item in version.document["references"]
                if item["id"] == module["referenceImageId"]
            ),
            None,
        )
        if reference is None or self.storage is None:
            raise AppError("REVERSE_REFERENCE_NOT_FOUND", "反推模块参考图不存在", 404)
        stored = await self.storage.get(reference["storageKey"])
        if stored is None:
            raise AppError("REVERSE_REFERENCE_NOT_FOUND", "反推模块参考图对象不存在", 404)
        return [stored.data], [stored.content_type]

    async def put_binding(
        self,
        project_id: UUID,
        *,
        target: str,
        scope: str,
        version_id: UUID,
        target_module_id: str | None,
        source_module_id: str | None,
    ):
        if self.project_repository is None:
            raise AppError("PROJECT_SERVICE_UNAVAILABLE", "业务项目服务不可用", 503)
        project = await self.project_repository.get_project(project_id, self.workspace_id)
        if project is None:
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        version = await self.get_version(version_id)
        reverse_project = await self.get_project(version.reverse_project_id)
        if scope == "overall":
            if target_module_id is not None or source_module_id is not None:
                raise AppError("REVERSE_BINDING_INVALID", "整体绑定不能指定模块", 400)
            source_title = None
        else:
            if not target_module_id or not source_module_id:
                raise AppError("REVERSE_BINDING_INVALID", "模块绑定必须指定目标和来源模块", 400)
            source = next(
                (item for item in version.document["modules"] if item["id"] == source_module_id),
                None,
            )
            if source is None:
                raise AppError("REVERSE_MODULE_NOT_FOUND", "反推模块不存在", 404)
            source_title = source["title"]
        return await self.repository.put_binding(
            self.workspace_id,
            project_id,
            project.name,
            target,
            scope,
            target_module_id,
            version,
            reverse_project.name,
            source_module_id,
            source_title,
        )

    async def list_project_bindings(self, project_id: UUID, target: str | None = None):
        if self.project_repository is None or await self.project_repository.get_project(
            project_id, self.workspace_id
        ) is None:
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        return await self.repository.list_project_bindings(
            self.workspace_id, project_id, target
        )

    async def list_reverse_bindings(self, reverse_project_id: UUID):
        return await self.repository.list_reverse_bindings(
            self.workspace_id, reverse_project_id
        )

    async def delete_binding(self, project_id: UUID, binding_id: UUID) -> bool:
        if self.project_repository is None or await self.project_repository.get_project(
            project_id, self.workspace_id
        ) is None:
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        deleted = await self.repository.delete_binding(
            self.workspace_id, project_id, binding_id
        )
        if not deleted:
            raise AppError("REVERSE_BINDING_NOT_FOUND", "反推绑定不存在", 404)
        return True

    @staticmethod
    def _document(project) -> dict[str, Any]:
        return {
            "name": project.name,
            "category": project.category,
            "summary": project.summary,
            "suitableFor": project.suitable_for,
            "goal": project.goal,
            "requiredMaterials": project.required_materials,
            "notSuitableFor": project.not_suitable_for,
            "references": [
                {
                    "id": str(item.id),
                    "ordinal": item.ordinal,
                    "filename": item.filename,
                    "width": item.width,
                    "height": item.height,
                    "mimeType": item.mime_type,
                    "previewUrl": f"/api/reverse-projects/{project.id}/references/{item.id}/preview",
                    "storageKey": item.storage_key,
                }
                for item in project.references
            ],
            "overall": deepcopy(project.overall),
            "modules": deepcopy(project.modules),
        }

    @staticmethod
    def _validate_publishable(document: dict[str, Any]) -> None:
        introduction = [
            document["name"], document["category"], document["summary"],
            document["suitableFor"], document["goal"], document["requiredMaterials"],
            document["notSuitableFor"],
        ]
        reference_ids = {item["id"] for item in document["references"]}
        try:
            ReverseOverall.model_validate(document["overall"])
            modules = [ReverseModule.model_validate(item) for item in document["modules"]]
        except ValidationError:
            modules = []
        valid_modules = bool(modules) and len({item.id for item in modules}) == len(modules)
        valid_modules = valid_modules and all(item.referenceImageId in reference_ids for item in modules)
        if (
            not all(isinstance(value, str) and value.strip() for value in introduction)
            or not reference_ids
            or not valid_modules
        ):
            raise AppError(
                "REVERSE_PROJECT_NOT_PUBLISHABLE",
                "发布前请补全参考图、项目介绍、整体策略和有效模块",
                400,
            )
