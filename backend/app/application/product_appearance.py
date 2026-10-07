"""Module-level contracts for deciding how a product enters an ecommerce image."""

from __future__ import annotations


_CONTRACTS: dict[str, str] = {
    "hero-kv": "必须出现完整产品，承担第一眼识别；不使用纯氛围或无产品画面。",
    "hero-overview": "必须出现完整产品，突出外观、比例和材质；与首屏 KV 使用不同角度或环境。",
    "hero-detail": "必须出现局部或细节特写，突出材质、纹理或关键结构；不得再次完整摆拍。",
    "hero-scene": "必须处于使用状态，例如手持、打开、佩戴、饮用或操作；禁止只把产品放在场景中。",
    "hero-colors": "必须出现已确认的多个颜色或组合；没有提供的颜色、型号或组合不得补造。",
    "hero-compare": "按已确认的比较事实决定；结构卖点用局部或关系图，抽象信息可以不出现产品；不得补造竞品或效果。",
    "hero-package": "必须出现已确认的产品、包装或配件，表现开箱或组合关系；未确认的内容不得补造。",
    "hero-benefit": "默认不出现产品，重点表现已确认的服务、质保或购买保障；需要产品时只能作为小比例辅助元素。",
    "suite-hero": "必须出现完整产品，建立商品识别；可以有轻微使用关系，但不得复用主图的机位和摆法。",
    "suite-benefit": "按卖点决定：结构卖点用局部或细节，使用卖点用行为状态，抽象卖点可以不出现产品；禁止默认整件居中。",
    "suite-scene": "必须处于使用状态，明确表现手持、打开、佩戴、饮用、食用、连接或操作；禁止无行为静物摆拍。",
    "suite-angle": "必须出现完整产品，每张突出一个明确角度；保持真实结构，不重复正面静置姿势。",
    "suite-mood": "默认可以不出现产品；出现时只作为环境参与者，不占画面主体，不做产品主视觉。",
    "suite-detail": "必须出现局部细节，使用近距离特写解释材质、纹理或结构；不得再次完整摆拍。",
    "suite-story": "默认不强制出现产品，优先表现已确认的品牌理念、来源或缘起；没有事实时不编造故事。",
    "suite-size": "必须出现产品与参照关系，清楚支持已确认的尺寸、容量或尺码；不做普通主视觉。",
    "suite-effect": "只有存在已确认的前后状态或可验证事实时才出现；资料不足时不得暗示功效或强行生成对比。",
    "suite-spec": "产品可完整、局部或不出现，由参数理解需要决定；规格信息优先，不再做产品主视觉。",
    "suite-craft": "默认不出现产品；没有真实工艺、原料或生产资料时，不虚构生产线、工艺阶段或产品过程。",
    "suite-accessory": "必须出现已确认的配件或包装内容，建立与产品的组合关系；未确认的赠品不得补造。",
    "suite-series": "必须出现已确认的系列产品或型号；没有多个真实产品时不得生成系列或补造差异。",
    "suite-ingredient": "按已确认的成分或材料决定；可以不出现完整产品，只保留局部包装或成分信息关系。",
    "suite-support": "默认不出现产品，重点表现已确认的售后或服务政策；产品出现时只能是辅助元素。",
    "suite-guide": "必须体现具体使用步骤或操作状态，产品处于打开、使用、倒出、收纳或拆装中；不能用静置产品代替步骤。",
    "suite-buyer": "必须处于真实使用情境，例如手持、饮用、佩戴或操作中；禁止产品单独摆拍。",
    "suite-creator": "必须有推荐行为或互动关系，例如手持讲解、展示细节或使用体验；禁止做成普通静置商品图。",
}


ALL_PRODUCT_APPEARANCE_MODULE_IDS = tuple(_CONTRACTS)


def product_appearance_contract(module_id: str) -> str:
    """Return the strongest known product appearance rule for a module."""

    return _CONTRACTS.get(
        module_id,
        "先判断产品是否需要出场；需要时明确行为、互动对象和状态，不需要时不得为了展示产品而强行加入。",
    )


def product_appearance_contract_prompt() -> str:
    """Return the planner instruction that maps catalog module IDs to contracts."""

    lines = [
        "【模块级产品出场契约】",
        "先根据 module.id 匹配下列契约，先决定产品是否出场，再决定产品行为、互动对象、视角、位置和占比。",
        "契约中的‘必须’优先于一般构图偏好；契约中的‘默认不出现’允许图片完全由环境、信息图形或人物行为承担主视觉。",
        "套图内完整静置产品图最多一张；已经出现完整静置展示后，后续优先改用局部、行为化、比例关系或无产品表达。",
    ]
    lines.extend(f"- {module_id}：{contract}" for module_id, contract in _CONTRACTS.items())
    return "\n".join(lines) + "\n"
