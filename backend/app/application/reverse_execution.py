"""Domain rules for turning a published reverse analysis into executable tasks."""

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4


_STRUCTURE_FIELDS = (
    ("goal", "goal"),
    ("layout", "layout"),
    ("informationHierarchy", "informationHierarchy"),
    ("typography", "typography"),
    ("colorAndLighting", "colorAndLighting"),
    ("adaptationNotes", "adaptationNotes"),
)


def build_execution_plan(document: dict[str, Any], version_id: UUID) -> dict[str, Any]:
    """Create a stable one-to-one execution outline from a reverse document.

    References are the source of truth for task count and order. Modules are
    attached by referenceImageId, so a module can never silently point at a
    different template image after the reference list is reordered.
    """
    references = sorted(
        (deepcopy(item) for item in document.get("references", [])),
        key=lambda item: (int(item.get("ordinal", 0)), str(item.get("id", ""))),
    )
    modules_by_reference = {
        str(module.get("referenceImageId")): module
        for module in document.get("modules", [])
        if module.get("referenceImageId")
    }
    tasks: list[dict[str, Any]] = []
    for ordinal, reference in enumerate(references, 1):
        reference_id = str(reference.get("id", ""))
        module = modules_by_reference.get(reference_id)
        structure = {
            output_key: str(module.get(input_key, "")) if module else ""
            for input_key, output_key in _STRUCTURE_FIELDS
        }
        if module is None:
            overall = document.get("overall") or {}
            structure["goal"] = str(overall.get("moduleStrategy", ""))
            structure["colorAndLighting"] = str(overall.get("visualSystem", ""))
            structure["adaptationNotes"] = str(overall.get("adaptationRules", ""))
        tasks.append(
            {
                "id": str(uuid4()),
                "ordinal": ordinal,
                "referenceImageId": reference_id,
                "referenceFilename": str(reference.get("filename", "")),
                "referencePreviewUrl": reference.get("previewUrl"),
                "referenceModuleId": str(module["id"]) if module else None,
                "title": str(module.get("title") if module else reference.get("filename", f"模板图 {ordinal}")),
                "structure": structure,
                "moduleParameters": [],
                "parametersAssigned": False,
                "promptDraft": "",
                "status": "draft",
            }
        )
    return {
        "versionId": str(version_id),
        "referenceCount": len(references),
        "tasks": tasks,
        "revision": 1,
    }


def compile_task_prompt(task: dict[str, Any], product_facts: dict[str, Any] | None = None, output_settings: dict[str, Any] | None = None) -> str:
    """Compile an auditable prompt while keeping the reference structure explicit."""
    structure = task.get("structure") or {}
    facts = product_facts or {}
    # Before 自动填写 runs, preserve the legacy behavior of making all
    # confirmed facts available to every prompt. Once the planner has marked
    # a task as assigned, restrict facts to the values allocated to that task.
    if task.get("parametersAssigned") or task.get("moduleParameters"):
        facts = {key: value for key, value in facts.items() if key == "商品名称"}
        facts.update({item["key"]: item["value"] for item in task["moduleParameters"] if item.get("key", "").strip() and item.get("value", "").strip()})
    facts_text = "；".join(f"{key}：{value}" for key, value in facts.items() if str(value).strip()) or "以当前项目已确认商品事实为准"
    return "\n".join(
        [
            "项目反推执行任务。依据下列模块拆解保持模板结构与信息职责。",
            "输入图片只用于确认当前商品的外形、结构、颜色、材质和标识；不沿用输入图片的背景。",
            f"任务：{task.get('title', '')}",
            f"目标：{structure.get('goal', '')}",
            f"场景与构图：{structure.get('layout', '')}",
            "产品呈现约束：机位与产品姿态以场景与构图中的拆解描述为准。"
            "将当前商品作为真实三维物体重新摆放和拍摄，不得沿用商品输入图的拍摄角度和摆放方向，"
            "也不能仅在二维画面中旋转原图来代替机位变化。"
            "画面左右均以观看者为准，按拆解中前端与后端的部件锚点、长轴方向、可见面和俯视高度呈现商品；"
            "主体数量、画面位置、占画比例、留白、裁切和遮挡关系须与拆解描述一致，接触面和投影须自然。"
            "不得通过镜像翻转商品来满足朝向，不能为突出卖点自行改成更高的俯视或另一个可见侧面。"
            "商品的真实结构、部件位置、比例、颜色、材质、纹样和标识仍以商品输入图及已确认事实为准，"
            "不得为模仿参考商品而删除当前商品的线缆、按键、接口等部件，不编造未确认的结构。",
            f"信息层级：{structure.get('informationHierarchy', '')}",
            f"字体与文字区域：{structure.get('typography', '')}",
            f"色彩与光影：{structure.get('colorAndLighting', '')}",
            f"适配要求：{structure.get('adaptationNotes', '')}",
            f"当前商品事实：{facts_text}",
            f"输出语言：{(output_settings or {}).get('outputLanguage', '中文')}。需要文字时只使用本图分配的事实；模板要求无字时保持无字。",
            "按拆解描述重新生成场景与道具，遵循描述中的机位、主体摆位、留白关系、色彩和光影；"
            "仅未描述的背景和道具细节可合理设计，不得借此改变已有的产品呈现约束。",
            "商品以输入图片和当前商品事实为准；参考分析中的其他商品、品牌、参数及宣传文案不得直接沿用或编造成当前商品事实。",
        ]
    )
