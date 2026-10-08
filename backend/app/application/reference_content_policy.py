"""Keep reference design reusable without carrying over third-party overlays."""

import re


REFERENCE_ANALYSIS_POLICY = (
    "只迁移参考页已有的构图、主体数量与占比、透视、场景、道具、光影、排版层级和视觉节奏；"
    "不新增参考页没有的场景、粒子、烟雾、装置或装饰，信息模糊时保守处理。"
    "平台、店铺、版权水印和漂浮在背景上的第三方标识是叠加图层，不属于可迁移设计；"
    "不要把它们写入背景、道具、信息层级、字体、光影或适配要求。"
    "商品本体印刷、铭牌、刻字和包装标识与水印分开记录，替换商品后只保留当前商品图里的真实标识。"
    "参考品牌、标题和参数只说明其信息职责及文字布局，不作为当前商品事实；"
    "当前商品名称、卖点、参数、细节和品牌由用户确认的信息提供，不复制参考数字、型号、认证或宣传结论。"
    "没有文字的模块不加文字，少文字的模块不扩写；不指定与参考光影冲突的电影光照或与输出设置冲突的分辨率。"
)

REFERENCE_OVERLAY_GUARD = (
    "不生成参考图中的平台、店铺或版权水印，不添加作为第三方水印的背景Logo、站点名称、半透明大字或版权叠加标记。"
    "参考页原有的半透明文字排版可保留，但内容只能使用当前商品已确认的信息。"
    "保留商品输入图中印在产品本体、铭牌或包装上的真实品牌Logo和标识，不能把它们当作水印删除。"
)

_OVERLAY = re.compile(
    r"水印|\bwatermarks?\b|版权(?:标记|叠加|标识)|"
    r"(?:电商|购物|销售)?平台\s*(?:的)?\s*(?:logo|标识|标志)|"
    r"店铺\s*(?:的)?\s*(?:logo|标识|标志)|"
    r"(?:JD\s*\.?\s*COM|京东|淘宝|天猫|拼多多)\s*(?:平台)?\s*(?:大字|标识|logo)",
    re.IGNORECASE,
)
_CLAUSES = re.compile(r"([^。；;\n]+)([。；;\n]*)")
_NEGATED_BEFORE = re.compile(
    r"(?:不得|不要|不应|不能|不可|不含|不带|不添加|不生成|不复制|不继承|不出现|"
    r"禁止|避免|没有|无|忽略|排除|去除|清除|删除|移除)"
    r"(?:生成|添加|复制|继承|出现|当作|任何|一切|参考图中|参考图|原图中|原图|"
    r"背景上|背景|平台|店铺|版权|第三方|半透明|漂浮|叠加|的|\s)*$"
)
_NEGATED_AFTER = re.compile(
    r"^\s*(?:(?:不得|不要|不应|不能|禁止|无需)(?:生成|添加|复制|继承|出现|输出)|"
    r"不复制|不继承|不输出)"
)
_DEPENDENT_FRAGMENT = re.compile(r"^(?:位于|位处|处于|作为|用于|其|该|未遮挡|不遮挡)")
_REFERENCE_SECTIONS = (
    "任务：", "场景与构图：", "目标：", "信息层级：", "字体与文字区域：",
    "色彩与光影：", "适配要求：",
)
_NON_REFERENCE_SECTIONS = (
    "项目反推执行任务。", "输入图片", "当前商品事实：", "商品身份优先：",
    "产品呈现约束：", "场景融合：", "输出语言：", "按拆解描述重新生成",
    "商品以输入图片", "不生成参考图中的平台、店铺或版权水印",
)


def clean_reference_text(value: str) -> str:
    """Remove overlay clauses only from reference descriptions, never facts."""
    return "".join(
        cleaned + separator for text, separator in _CLAUSES.findall(value)
        if (cleaned := _clean_sentence(text))
    ).strip()


def _positive_overlay(text: str) -> bool:
    return any(
        not _NEGATED_BEFORE.search(text[:match.start()])
        and not _NEGATED_AFTER.search(text[match.end():])
        for match in _OVERLAY.finditer(text)
    )


def _clean_sentence(text: str) -> str:
    if not _positive_overlay(text):
        return text
    # Split only independent, top-level clauses. Commas inside coordinate
    # pairs or parentheses are part of the same description.
    parts, start, depth = [], 0, 0
    for index, character in enumerate(text):
        if character in "(（[【":
            depth += 1
        elif character in ")）]】":
            depth = max(0, depth - 1)
        elif character in "，," and depth == 0:
            parts.append((text[start:index], character))
            start = index + 1
    parts.append((text[start:], ""))
    kept, excluded = [], False
    for part, separator in parts:
        if _positive_overlay(part):
            excluded = True
            continue
        if excluded and _DEPENDENT_FRAGMENT.match(part.lstrip()):
            continue
        kept.append(part + separator)
        excluded = False
    return "".join(kept).rstrip("，,")


def prepare_reference_prompt(prompt: str) -> str:
    """Sanitize cached reference sections before freezing a new batch prompt.

    Current-product facts and manually entered product branding stay intact.
    Call this before batch creation; historical retry prompts remain frozen.
    """
    lines = []
    reference_section = False
    for line in prompt.splitlines():
        stripped = line.lstrip()
        prefix = next((prefix for prefix in _REFERENCE_SECTIONS if stripped.startswith(prefix)), None)
        if prefix is not None:
            reference_section = True
            content = clean_reference_text(stripped[len(prefix):])
            cleaned = prefix + content if content else ""
        else:
            if stripped.startswith(_NON_REFERENCE_SECTIONS):
                reference_section = False
            cleaned = clean_reference_text(line) if reference_section else line
        if cleaned:
            lines.append(cleaned)
    result = "\n".join(lines)
    if REFERENCE_OVERLAY_GUARD not in result:
        result += "\n" + REFERENCE_OVERLAY_GUARD
    return result
