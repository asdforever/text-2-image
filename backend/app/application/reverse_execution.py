"""Domain rules for turning a published reverse analysis into executable tasks."""

from copy import deepcopy
import re
from typing import Any
from uuid import UUID, uuid4

from .reference_content_policy import clean_reference_text, REFERENCE_OVERLAY_GUARD


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
        structure = {key: clean_reference_text(value) for key, value in structure.items()}
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


def _render_layout(layout: str) -> str:
    # Evidence and uncertainty belong to the saved analysis, not to the
    # photographer's execution brief. Leave the original task untouched.
    return "\n".join(line for line in layout.splitlines()
        if not line.strip().startswith(("观察依据：", "不确定项：")))


def _sentence(value: str) -> str:
    text = " ".join(value.splitlines()).strip().rstrip("；;")
    return text + ("" if not text or text.endswith(("。", "！", "？", ".", "!", "?")) else "。")


def _describe_layout(layout: str) -> str:
    """Turn analysis labels into shooting instructions without losing geometry."""
    text = re.sub(r"主体数量：\s*(\d+)", r"画面包含\1个主体", _render_layout(layout))
    for label, description in (
        ("场景与空间：", ""),
        ("位置与占画比例：", "主体的摆位及占画比例为"),
        ("相机机位：", "镜头采用"),
        ("产品朝向与长轴：", "商品摆放方向为"),
        ("前后端/部件锚点：", "参考姿态的前后端通过这些特征定位："),
        ("功能前端证据：", "功能前端定位依据为"),
        ("可见面：", "镜头中展示"),
        ("可见侧壁定位：", "可见侧壁对应"),
        ("裁切与遮挡：", "取景和遮挡保持如下关系："),
        ("接触与投影：", "承托及阴影表现为"),
    ):
        text = text.replace(label, description)
    return "".join(_sentence(line) for line in text.splitlines() if line.strip())


def compile_task_prompt(task: dict[str, Any], product_facts: dict[str, Any] | None = None, output_settings: dict[str, Any] | None = None, *, product_image_count: int = 1) -> str:
    """Compile current inputs as descriptive prose; keep analysis in the plan."""
    structure = {key: clean_reference_text(str(value)) for key, value in (task.get("structure") or {}).items()}
    facts = product_facts or {}
    # Before 自动填写 runs, preserve the legacy behavior of making all
    # confirmed facts available to every prompt. Once the planner has marked
    # a task as assigned, restrict facts to the values allocated to that task.
    if task.get("parametersAssigned") or task.get("moduleParameters"):
        facts = {key: value for key, value in facts.items() if key == "商品名称"}
        facts.update({item["key"]: item["value"] for item in task["moduleParameters"] if item.get("key", "").strip() and item.get("value", "").strip()})
    facts_text = "，".join(f"{key}为“{value}”" for key, value in facts.items() if str(value).strip())
    title = clean_reference_text(str(task.get("title", "")))
    layout = _describe_layout(structure.get("layout", ""))
    hierarchy = re.sub(r"(第[一二三四五六七八九十\d]+层)[:：]", r"\1突出", structure.get("informationHierarchy", ""))
    language = (output_settings or {}).get("outputLanguage", "中文")
    paragraphs = [
        "以输入商品图作为唯一外观参考，保持真实轮廓、结构、比例、颜色、材质、纹理、部件、配件、包装和实体Logo。"
        + (f"本页使用的已确认信息是{facts_text}。" if facts_text else "商品信息仅使用当前已确认资料。")
        + (f"为该商品创作{title}。" if title else "为该商品创作对应的电商页面。"),
        layout,
        ("画面的内容职责是" + _sentence(structure["goal"])) if structure.get("goal") else "",
        ("色彩与受光表现为" + _sentence(structure["colorAndLighting"])) if structure.get("colorAndLighting") else "",
        ("视觉阅读顺序为" + _sentence(hierarchy)) if hierarchy else "",
        ("文字排版采用" + _sentence(structure["typography"])) if structure.get("typography") else "",
        _sentence(structure.get("adaptationNotes", "")),
        "按上述机位、朝向、可见面与占画比例重新摆放和拍摄商品，不沿用输入图的拍摄姿态，不通过镜像或二维旋转代替。"
        "不擅自放大主体或改换可见侧面。"
        "参考页的商品颜色、部件和连接方式仅用于理解摆位，当前商品外观及结构始终以输入图为准，不删除真实部件或硬造结构。"
        "商品与场景共用同一相机透视，受光、反射、景深与环境一致，保留真实颜色材质，不出现抠图白边。"
        "有接触的支撑处生成贴合的阴影，悬浮或夹持时保留原支撑关系；有线商品保留线缆，从真实连接点自然弯曲，不穿插或硬折。"
        f"需要文字时使用{language}，标题、卖点与参数仅取自本页已确认信息，缺失信息不编造，无字页面保持无字。"
        "仅迁移已有场景、道具、光影和排版，信息缺失时保守补全，不新增装饰，不复制参考商品的品牌、型号、数字或宣传结论。"
        + REFERENCE_OVERLAY_GUARD,
    ]
    from .reverse_product_images import product_view_guidance
    return product_view_guidance(product_image_count) + "".join(paragraph for paragraph in paragraphs if paragraph)
