"""Adapt a pinned upstream Skill bundle into offline planning context."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


STYLE_LIBRARY_SOURCE = "https://github.com/freestylefly/awesome-gpt-image-2"
STYLE_LIBRARY_REVISION = "0dc09c46c8a30b1fdd89c18cc78a894dac2104e3"
STYLE_LIBRARY_VERSION = "freestylefly-style-library-v1"
_BUNDLE = Path(__file__).resolve().parents[1] / "data" / "gpt_image_2_style_library"


@lru_cache(maxsize=1)
def _bundle() -> tuple[str, dict[str, str], str]:
    files = {name: (_BUNDLE / name).read_text(encoding="utf-8") for name in
             ("style-library.json", "templates.md", "SKILL.md", "LICENSE")}
    parts = re.split(r'<a name="([^"]+)"></a>', files["templates.md"])
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    digest = sha256(json.dumps(files, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return files["style-library.json"], sections, digest


def _templates() -> list[dict[str, Any]]:
    raw, _, _ = _bundle()
    records = json.loads(raw)["templates"]
    return [{
        "id": t["id"], "title": t["title"]["zh"], "category": t["category"],
        "styles": t["styles"], "scenes": t["scenes"], "tags": t["tags"],
        "useWhen": t["useWhen"]["zh"], "guidance": t["guidance"]["zh"],
        "pitfalls": t["pitfalls"]["zh"], "exampleCaseIds": t["exampleCases"],
        "templateAnchor": t["anchor"],
        "templateSource": f"{STYLE_LIBRARY_SOURCE}/blob/{STYLE_LIBRARY_REVISION}/docs/templates.md#{t['anchor']}",
    } for t in records]


def resolve_style_template(template_id: str) -> dict[str, Any]:
    """Return an independent record and its original category template text."""
    for template in _templates():
        if template["id"] == template_id:
            template["promptTemplate"] = _bundle()[1][template["templateAnchor"]]
            return template
    raise KeyError(template_id)


def style_library_context(template_id: str = "") -> dict[str, Any]:
    """All template summaries for routing, or one selected template in full."""
    return {
        "source": STYLE_LIBRARY_SOURCE, "license": "MIT",
        "version": STYLE_LIBRARY_VERSION, "revision": STYLE_LIBRARY_REVISION,
        "contentSha256": _bundle()[2],
        "selectionRules": [
            "先按输出类型选择模板类别，再匹配视觉风格、场景与示例索引。按每张图的职责选择，不能只按商品品类选择。",
            "模板中的产品、品牌、价格、参数与文案都是示例，必须用当前商品的已确认事实替换。",
            "案例编号仅是来源索引；未提供案例图片和正文，不得假装看过案例或推断其构图。",
            "结构化指导优先按任务采用，模板正文包含同类别多个变体，仅参考与当前任务相符的部分。",
            "最终提示词依次安排主体与任务、构图布局、风格材质、文字标签、画幅规格和约束；此流程复用上游 Skill 的 Workflow。",
        ],
        "templates": [resolve_style_template(template_id)] if template_id else _templates(),
    }


STYLE_LIBRARY_PLANNING_RULES = """
【通用视觉 Skill 的应用约定】
输入 styleLibrary 为通用模板目录。先按本张图的职责选择类别，再考虑视觉风格与场景，
选择一个 styleTemplateId，不能把所有商品和所有模块固定成同一种视觉。标签仅作为建议，
不得凭标签改变商品事实或平台约束。不需要向用户增加模板选择步骤，按已有资料完成选择。
每个模块输出 styleTemplateId、visualStyleTags、sceneTags、referenceCaseIds、bigIdea、visualMechanism。
styleTemplateId 必须来自 templates 的 id；参考案例仅可从所选模板 exampleCaseIds 中选，
且只是出处索引，不代表已查看案例图片。bigIdea 用一句话说明画面表达，visualMechanism 写
主体与图形、环境或文字的具体关系。规格图和白底图可以采用清晰直接的陈列或图解，不强迫加特效。
这些字段只决定表达结构；配色、光线仍由模块规划器结合用户风格决定。
主体/任务、构图、材质、文字、画幅、约束都应在最终单张提示词中有明确安排。
辅助物和概念图形只能服务已确认卖点；视觉隐喻不是实测证据，不能生成未经证实的内部结构或实验图。
模型输出遵守 outputSchema，它描述数据结构，不是要复制的结果。顶层只输出 summary、visualRhythm、
productPresencePlan、layoutFamilies、modules、warnings，不输出 type、properties 或 schema 包装。
商品真实性、平台规则和用户明确要求优先于模板中的例子。
风格材质只作用于背景、辅助物和版式，不能把商品本体改成纸、金属或其他未经确认的材质。
品牌名未知不等于没有标识：保留源图可见 logo 的外观和位置，不猜品牌文字，不擅自删掉标识。
已知部件总数不代表已知每个部件的位置、名称和功能。源图未清晰展示的结构不得补造，
不能为凑齐数量而推断隐藏部件或要求换角度展示它们；改用已确认的总数文案和可见局部。
"""

