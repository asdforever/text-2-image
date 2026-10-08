"""Assign product facts to fixed reverse tasks without redesigning the template."""
import asyncio
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import AppError
from .module_planning_service import ModuleMasterRequest, Parameter


class TaskParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: str = Field(min_length=1, max_length=100)
    moduleParameters: list[Parameter] = Field(default_factory=list, max_length=20)


class ParameterAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(default="", max_length=2000)
    tasks: list[TaskParameters] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ReverseExecutionParameterPlanner:
    def __init__(self, *, planner, project_asset_service, config_service=None, prompt_models=None):
        self.planner = planner
        self.assets = project_asset_service
        self.config_service = config_service
        self.prompt_models = prompt_models

    async def assign(self, project_id: UUID, document: dict[str, Any]) -> dict[str, Any]:
        source_id = document.get("sourceAssetId")
        if not source_id:
            raise AppError("REVERSE_SOURCE_ASSET_REQUIRED", "请先选择商品原图或白底图", 400)
        _, source_object = await self.assets.get_asset_details(project_id, UUID(source_id))
        source = await self.assets.get_preview(project_id, UUID(source_id))
        from .reverse_product_images import load_product_images, normalize_auxiliary_ids, product_view_guidance
        auxiliary, _ = await load_product_images(self.assets, project_id, normalize_auxiliary_ids(document.get("auxiliarySourceAssetIds", []), source_id))
        planner, connection = self.planner, None
        if self.config_service and self.prompt_models:
            published = await self.config_service.get_published()
            bound = await self.prompt_models.bind(published.content, planner)
            planner, connection = bound.compiler, bound.snapshot
        system = (
            "你是轻量电商内容规划师。将当前商品资料分配到已有项目反推任务。"
            "图片仅为当前商品图；模板拆解只说明设计结构，不能把模板中的竞品参数当作当前商品事实。"
            "按每张任务的目标、信息层级和文字区域分配商品事实与创作约束，返回 moduleParameters 的 key/value。"
            "无字产品图只补商品外观与拍摄约束，不强加文案。不得编造尺寸、认证、价格或功效；"
            "无法确认的信息不填写，可以返回空参数列表。所有任务必须原样保留 taskId，一一对应，不新增或删减；"
            "不重新设计构图、场景、光影、排版，不修改拆解内容。只返回符合 outputSchema 的 JSON。"
        )
        context = {
            "parameterBrief": document.get("parameterBrief", ""),
            "productFacts": document.get("productFacts", {}),
            "outputLanguage": document.get("outputSettings", {}).get("outputLanguage", "中文"),
            "tasks": [{"id": task["id"], "ordinal": task["ordinal"], "title": task["title"], "structure": task["structure"]} for task in document.get("tasks", [])],
            "outputSchema": ParameterAssignment.model_json_schema(),
        }
        try:
            async with asyncio.timeout(540):
                raw = await planner.plan_modules(ModuleMasterRequest(system + product_view_guidance(1 + len(auxiliary)), json.dumps(context, ensure_ascii=False), [source.data, *(item.image_bytes for item in auxiliary)], [source_object.media_type, *(item.image_mime_type for item in auxiliary)]))
            result = ParameterAssignment.model_validate(raw).model_dump()
            ids = [task["taskId"] for task in result["tasks"]]
            expected = [task["id"] for task in document.get("tasks", [])]
            if len(ids) != len(expected) or len(set(ids)) != len(ids) or set(ids) != set(expected):
                raise ValueError("task identities changed")
        except (ValidationError, ValueError, TypeError) as exc:
            raise AppError("REVERSE_PARAMETERS_INVALID_RESPONSE", "自动填写结果未保持全部模板任务，请重试；原方案已保留", 502) from exc
        except TimeoutError as exc:
            raise AppError("REVERSE_PARAMETERS_TIMEOUT", "自动填写超时，请重试", 504) from exc
        except AppError:
            raise
        except Exception as exc:
            raise AppError("REVERSE_PARAMETERS_FAILED", "自动填写失败，请检查提示词模型配置后重试", 502) from exc
        return {**result, "promptModelConnection": connection}
