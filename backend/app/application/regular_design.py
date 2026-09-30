"""Short deterministic regular prompt, adapted from EvoLink product recipe principles.
Source: EvoLinkAI/gpt-image-2.5-for-e-commerce, revision 963b1f40bfbe5ff81f0c9684587face6a500bc9a.
CC BY 4.0 https://creativecommons.org/licenses/by/4.0/ .
Changes: removed example product facts; parameterized task, platform, style and output.
"""
import json

from ..core.errors import AppError


RECIPE = {
    "source_id": "evolink-product-local-v1",
    "source": "https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce",
    "revision": "963b1f40bfbe5ff81f0c9684587face6a500bc9a",
    "license": "CC-BY-4.0",
    "adaptation": "Single product identity-preserving image with suite-level consistency and module-specific scene direction; no inherited example facts or default counts",
}

_REGULAR_SUITE_CONSISTENCY = (
    "同一商品套图：每张图都必须保持同一商品的真实形状、比例、材质、颜色、纹理和可见标识一致；"
    "共享所选风格的色彩关系、品牌气质与光感；不要复制同一背景、同一机位、同一主体摆位，"
    "连续图片必须在场景、镜头距离、视角或版式上产生明显变化；禁止把风格种子中的背景描述当成每张图的固定模板。"
)

_REGULAR_MODULE_DIRECTIONS = {
    "suite-hero": "主视觉：完整展示商品，使用三分之四主视角，主体清晰占据画面核心并留出文案安全区；背景简洁，建立商品第一印象。",
    "suite-benefit": "卖点信息图：商品缩小到一侧或画面下方，用结构化信息卡、线条或局部示意表达当前卖点；避免再次做满幅商品特写。",
    "suite-detail": "局部微距：以材质、纹理、按键、接口或工艺为焦点，使用近距离特写和浅景深；不要重复完整商品主视图。",
    "suite-scene": "真实桌面使用场景：将商品放在真实桌面或工作环境，允许出现手部或相关使用动作；使用不同于主视觉的环境光和机位，避免纯科技棚拍背景。",
    "suite-size": "尺寸示意：使用中性浅色或干净技术背景，采用正交、侧视或俯视角度和清晰尺寸标注；商品完整可辨，不加入未经提供的参数。",
    "suite-spec": "参数表：使用规整的产品参数表或信息卡布局，商品约占画面三分之一并留出清晰文字区域；文字只使用已提供的商品事实。",
    "suite-mood": "生活方式氛围：选择与商品匹配的生活场景或桌面氛围，变化背景材质、景别和机位；保持商品是主角，不复制主视觉的几何科技棚。",
    "suite-angle": "多角度展示：使用正面、侧面、背面或俯视等明确角度之一，强调视角差异并保持商品结构、比例和细节一致。",
}


def regular_suite_consistency() -> str:
    return _REGULAR_SUITE_CONSISTENCY


def regular_module_direction(module_id: str) -> str:
    return _REGULAR_MODULE_DIRECTIONS.get(
        module_id,
        "模块专属场景：根据当前模块目标设计独立的场景、机位和版式，与其它模块拉开差异；不要复制其它图片的背景和主体摆位。",
    )


def regular_snapshot(request, selected, master, module, parameters, market, style, constraints):
    if master and master.get("planningContractVersion") != "regular-design-v1":
        raise AppError("MODULE_PLAN_MODE_MISMATCH", "规划模式不匹配，请重新规划", 409)
    task_id = selected.task_id or selected.module_id
    outline = next(
        (
            m
            for m in (master or {}).get("modules", [])
            if (m.get("taskId") or m["moduleId"]) == task_id and m["moduleId"] == selected.module_id
        ),
        None,
    )
    if master and outline is None:
        raise AppError("MODULE_PLAN_TASK_MISMATCH", "模块不属于当前规划", 409)
    task = selected.regular_task if selected.regular_task is not None else {
        "goal": (outline or {}).get("reason", ""),
        "copy": (outline or {}).get("suggestedCopy", ""),
    }
    if set(task) != {"goal", "copy"} or any(not isinstance(v, str) or len(v) > 2000 for v in task.values()):
        raise AppError("REGULAR_TASK_INVALID", "内容目标与文案无效", 400)

    facts = parameters
    suite_consistency = regular_suite_consistency()
    module_direction = regular_module_direction(selected.module_id)
    module_variation = (
        f"本图围绕当前目标“{task['goal']}”选择与其它同类图片不同的局部区域、机位或信息排布；"
        "如果套图中出现多个同类型模块，也不要复用同一主体摆位。"
    )
    context = {
        "goal": task["goal"],
        "approvedCopy": task["copy"],
        "assignedProductFacts": facts,
        "platform": market.get("label", request.market_id),
        "platformRules": constraints.market.content,
        "style": constraints.style.content,
        "customStyle": request.custom_style,
        "suiteConsistency": suite_consistency,
        "moduleDirection": module_direction,
        "moduleVariation": module_variation,
        "styleApplication": "将风格种子作为配色、品牌气质和光感参考；优先执行当前模块的场景与构图方向，不复制风格种子中的固定背景。",
        "module": {
            "id": selected.module_id,
            "label": module.get("label", selected.module_id),
            "description": module.get("description", ""),
        },
        "output": {
            "aspectRatio": request.aspect_ratio,
            "resolution": request.resolution,
            "language": request.output_language,
        },
        "userNotes": getattr(request, "user_notes", ""),
    }
    prompt = (
        "Create one ecommerce image for the supplied product. Preserve its actual shape, materials, colors and markings. "
        "Use only supplied facts; do not invent claims, prices, certifications or extra text. "
        "Render approvedCopy in the requested language, respecting platform restrictions. No collage. "
        "This is one image in a coherent product suite: obey suiteConsistency, then obey the moduleDirection and moduleVariation for this image. "
        "The module direction controls the scene, camera and layout; the style seed does not force a repeated background.\n"
        + json.dumps(context, ensure_ascii=False)
    )
    return {
        "creationMode": "regular",
        "plannerVersion": "regular-design-v1",
        "taskId": task_id,
        "moduleId": selected.module_id,
        "module": module,
        "title": (outline or {}).get("taskTitle", module.get("label", selected.module_id)),
        "regularTask": task,
        "moduleParameters": facts,
        "compiledTaskPrompt": prompt,
        "recipe": dict(RECIPE),
        "suiteConsistency": suite_consistency,
        "moduleDirection": module_direction,
        "moduleVariation": module_variation,
        "selection": {
            "market": market,
            "style": style,
            "module": module,
            "moduleParameters": facts,
            "aspectRatio": request.aspect_ratio,
            "resolution": request.resolution,
            "outputLanguage": request.output_language,
        },
        "constraints": constraints.to_snapshot(),
    }


def render_regular(snapshot):
    prompt = snapshot.get("compiledTaskPrompt")
    if not isinstance(prompt, str) or not prompt.strip() or not snapshot.get("recipe"):
        raise AppError("MODULE_PLANNING_SNAPSHOT_INVALID", "常规模式快照无效", 500)
    return prompt
