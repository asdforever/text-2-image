"""Short deterministic regular prompt, adapted from EvoLink product recipe principles.
Source: EvoLinkAI/gpt-image-2.5-for-e-commerce, revision 963b1f40bfbe5ff81f0c9684587face6a500bc9a.
CC BY 4.0 https://creativecommons.org/licenses/by/4.0/ .
Changes: removed example product facts; parameterized task, platform, style and output.
"""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import AppError
from .product_appearance import product_appearance_contract


class RegularTaskOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    copyPolicy: Literal['fixed', 'flexible'] = 'flexible'
    visualRequirements: str = Field(default='', max_length=2000)


RECIPE = {
    "source_id": "evolink-product-local-v1",
    "source": "https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce",
    "revision": "963b1f40bfbe5ff81f0c9684587face6a500bc9a",
    "license": "CC-BY-4.0",
    "adaptation": "Single product identity-preserving image with suite-level consistency and module-specific scene direction; no inherited example facts or default counts",
}

_REGULAR_SUITE_CONSISTENCY = (
    "同一商品套图：产品出场时必须保持同一商品的真实形状、比例、材质、颜色、纹理和可见标识一致；"
    "某张图不需要产品时，不强行加入产品；"
    "同一套图完整静置产品图最多一张，后续优先改用局部、行为化、比例关系或无产品表达；"
    "共享所选风格的色彩关系、品牌气质与光感；不要复制同一背景、同一机位、同一主体摆位，"
    "连续图片必须在场景、镜头距离、视角或版式上产生明显变化；禁止把风格种子中的背景描述当成每张图的固定模板。"
)

_REGULAR_PRODUCT_APPEARANCE_GUIDANCE = (
    "每张常规版图片生成前，先判断产品是否需要出场；如果需要，明确具体行为或状态，"
    "例如静置、佩戴、手持、打开、使用中、食用中、倒出、连接、收纳或拆装，并明确它与人物、手部、环境或其他产品的互动关系，"
    "再决定视角、位置、占比和版式；如果不需要，不要为了展示产品而强行加入。"
    "不能只写‘放在场景中’，行为必须符合商品品类和已提供事实，不能暗示未经确认的功能或功效；"
    "同一套图要避免重复相同的产品行为、姿势和出场方式。"
    "模块方向中的产品出场契约优先于一般构图偏好；契约要求不出现时，最终提示词不得补回产品。"
)

_REGULAR_MODULE_DIRECTIONS = {
    "suite-hero": "主视觉：先根据当前目标判断产品是否需要出场；需要识别时完整展示，强调使用关系时可通过行为化出场，不默认静置三分之四商品照；背景简洁，建立清晰第一印象。",
    "suite-benefit": "卖点信息图：先判断卖点是否需要产品作为证据，可用完整、局部、行为化出场或不出场；再用结构化信息卡、线条或局部示意表达当前卖点，避免默认满幅商品特写。",
    "suite-detail": "局部微距：以材质、纹理、按键、接口或工艺为焦点，使用近距离特写和浅景深；不要重复完整商品主视图。",
    "suite-scene": "真实使用场景：优先判断是否存在具体的佩戴、手持、打开、操作、食用或连接行为；可在真实桌面或其它真实环境中让产品完整、局部或作为场景参与者出场，也可在不需要时不出场；避免无行为的静物摆拍。",
    "suite-size": "尺寸示意：使用中性浅色或干净技术背景，采用正交、侧视或俯视角度和清晰尺寸标注；商品完整可辨，不加入未经提供的参数。",
    "suite-spec": "参数表：先判断产品是否是理解参数所必需的证据；可以缩小、局部展示或不出场，再使用规整的参数表或信息卡布局；文字只使用已提供的商品事实。",
    "suite-mood": "生活方式氛围：选择与商品匹配的生活场景或桌面氛围，产品是否出场由当前目标决定；可以让人物、食材、材质或环境承担主视觉，变化背景材质、景别和机位，不复制主视觉的几何科技棚。",
    "suite-angle": "多角度展示：使用正面、侧面、背面或俯视等明确角度之一，强调视角差异并保持商品结构、比例和细节一致。",
}


def regular_suite_consistency() -> str:
    return _REGULAR_SUITE_CONSISTENCY


def regular_product_appearance_guidance() -> str:
    return _REGULAR_PRODUCT_APPEARANCE_GUIDANCE


def regular_module_direction(module_id: str) -> str:
    direction = _REGULAR_MODULE_DIRECTIONS.get(
        module_id,
        "模块专属场景：根据当前模块目标设计独立的场景、机位和版式，与其它模块拉开差异；不要复制其它图片的背景和主体摆位。",
    )
    return f"{direction} 产品出场契约：{product_appearance_contract(module_id)}"


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
        "优先改变产品行为、出场方式或互动关系，其次再改变机位和版式；如果套图中出现多个同类型模块，也不要复用同一主体摆位。"
    )
    planned_modules = (master or {}).get("modules", [])
    if planned_modules:
        suite_modules = [
            {
                "taskId": m.get("taskId") or m.get("moduleId"),
                "moduleId": m.get("moduleId", ""),
                "taskTitle": m.get("taskTitle", ""),
                "goal": m.get("reason", ""),
                "copy": m.get("suggestedCopy", ""),
            }
            for m in planned_modules
            if isinstance(m, dict)
        ]
    else:
        suite_modules = []
        for item in getattr(request, "modules", []):
            item_task = getattr(item, "regular_task", None) or {}
            suite_modules.append({
                "taskId": getattr(item, "task_id", None) or getattr(item, "module_id", ""),
                "moduleId": getattr(item, "module_id", ""),
                "taskTitle": getattr(item, "module_id", ""),
                "goal": item_task.get("goal", ""),
                "copy": item_task.get("copy", ""),
            })
    context = {
        "goal": task["goal"],
        "approvedCopy": task["copy"],
        "assignedProductFacts": facts,
        "platform": market.get("label", request.market_id),
        "platformRules": constraints.market.content,
        "style": constraints.style.content,
        "customStyle": request.custom_style,
        "suiteConsistency": suite_consistency,
        "productAppearanceGuidance": regular_product_appearance_guidance(),
        "suiteModules": suite_modules,
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
    options = getattr(selected, 'regular_options', None)
    try:
        options = RegularTaskOptions.model_validate({} if options is None else options).model_dump()
    except ValidationError:
        raise AppError('REGULAR_OPTIONS_INVALID', '文案策略或视觉要求无效', 400) from None
    context.update(options)
    context['lockedInformation'] = '品牌、商品参数、指定原文及商品事实必须准确；不得新增未经提供的功能、功效、价格或认证。'
    context['currentInputPriority'] = (
        'assignedProductFacts 是本图最新补充的事实与要求，在真实性和平台规则范围内优先于旧 goal、文案建议及套图规划。'
        '旧规划声称某项信息未提供时，如最新参数已提供该信息，应采用最新参数；按参数含义区分商品事实、服务承诺与设计要求，'
        '设计要求不得误当作上图文案。flexible 时按本图目标组织相关参数的文案，suggestedCopy 仅作参考；'
        'fixed 时 approvedCopy 必须原样保留，不自行改写或扩写。不得虚构参数之外的承诺或信息。'
    )
    if options['copyPolicy'] == 'flexible':
        context['suggestedCopy'] = context.pop('approvedCopy')
    copy_instruction = (
        'Compose concise copy based on suggestedCopy and supplied facts in the requested language; preserve lockedInformation and respect platform restrictions. No collage. '
        if options['copyPolicy'] == 'flexible' else
        'Render approvedCopy in the requested language, respecting platform restrictions. No collage. '
    )
    prompt = (
        "Create one ecommerce image for the supplied product. If the product appears, preserve its actual shape, materials, colors and markings. "
        "Use only supplied facts; do not invent claims, prices, certifications or extra text. "
        "Follow currentInputPriority when current parameters conflict with older planning assumptions. "
        + copy_instruction +
        "This is one image in a coherent product suite: obey suiteConsistency, then obey the moduleDirection and moduleVariation for this image. "
        "The module direction controls the scene, camera and layout; the style seed does not force a repeated background. "
        "Before composing the image, follow productAppearanceGuidance to decide whether the product appears and what behavior or state it has; "
        "use suiteModules to make this image complementary to the other planned modules; the behavior decision must guide the composition instead of defaulting to a repeated static product pose. "
        "A module may intentionally omit the product when the scene, material, action or atmosphere communicates the goal better.\n"
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
        'regularOptions': options,
        "moduleParameters": facts,
        "compiledTaskPrompt": prompt,
        "recipe": dict(RECIPE),
        "suiteConsistency": suite_consistency,
        "productAppearanceGuidance": regular_product_appearance_guidance(),
        "suiteModules": suite_modules,
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
