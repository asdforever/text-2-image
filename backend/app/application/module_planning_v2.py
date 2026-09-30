from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from ..core.errors import AppError
from .design_knowledge import design_knowledge_context, load_design_knowledge
from .image_style_library import style_library_context
from .commerce_design import commerce_design_context
from .task_design import resolve_task_design


PLANNER_VERSION_V2 = "v2"
V2_RENDERER_VERSION = "module-renderer-v2.1"
V2_COMPOSER_VERSION = "final-composer-v2.1"


SYSTEM_PROMPT_BASE = (
    "你是电商图片模块规划器。你要直接写出一段可交给图片模型的画面描述提示词。\n\n"

    "【任务】\n"
    "根据固定风格种子、源图可见信息、模块任务和约束，为当前模块写一段中文画面描述。"
    "这段描述会被直接交给图片模型执行，所以它必须是描述式的自然语言，"
    "不是字段清单、不是表单、不是分析过程。\n\n"

    "【imagePrompt 的写法】\n"
    "按读图顺序组织：先根据 taskOutline 的 productPresence 决定商品出场方式：full 才完整展示商品，"
    "partial、detail、context、none 不得自动补回完整商品；再写主体、视角与占比，"
    "以及画面中实际可见的品牌标识外观与位置；"
    "再视角与构图（机位、角度、主体位置、留白的位置与用途）；"
    "再视觉基调（配色关系、光线方向与质感、背景处理方式）；最后是画面上允许出现的文字。\n"
    "只写画面里能看到的东西。用具体名词和形容词，不用「高级」「大气」这类空话。\n"
    "用逗号和句号连成连贯段落，不要用分号罗列字段，不要加任何字段名或标签。\n"
    "不写「模块」「模块目标」「信息层级」「本图任务」这类内部概念。\n"
    "按模块类型控制长度：主图模块（module.mode = hero）不超过 350 字，"
    "详情页模块（module.mode = suite）不超过 600 字。"
    "结尾约束无水印、无无关道具、无未经授权的促销角标与认证徽章。"
    "允许服务本图表达且不违背平台规则的辅助物和概念图形。\n\n"

    "【风格】\n"
    "保留所选风格的配色方向、品牌气质及用户明确要求，以 sharedVisualDirection 统一系列。"
    "风格种子中的默认光照、环境、机位是执行建议，可按本图任务调整；信息图不必棚拍，"
    "使用场景不必复制首图背景。用户明确指定的光照或构图必须遵守。"
    "风格种子或模板中的纸纹、金属等材质描述只作用于背景、辅助物与版式，"
    "不能改写商品本体的材质、颜色、纹理和结构。\n\n"

    "【设计指导与任务优先级】\n"
    "读取 commerceDesign 中实际提供的规则，先明确本图信息问题、事实证据和视觉解释。"
    "商品事实和适用平台规则优先，其次用户明确要求，再是本图信息目标和出场方式，最后才是"
    "可调整的 compositionAdvice、模块名称和模板建议。explicitCompositionRequirements 是用户构图要求，"
    "不是上图文案或商品事实。"
    "explicitTaskDesign 是用户对本张图的最新设计选择，优先于自动任务书及旧构图建议；"
    "taskOutline 已合并这些选择。用户填写的标题、信息目标和表达方式不是商品事实，也不是必须上图的文案。"
    "productPresence=auto 表示用户把出场方式交给你按目标判断；显式留空的设计字段表示解除原有要求。"
    "当出场方式改变时，同步调整旧建议中的商品构图，不得用旧建议撤销用户选择。"
    "compositionAdvice 可以优化，不能因模块名把 none 自动改回完整产品。"
    "若用户明确要求改变出场方式，在 visualDirection 说明调整原因，并核对商品事实及平台约束。"
    "placement=primary 是首图、gallery 是附图、detail 是详情图；按规则适用范围执行，"
    "仅限首图的要求不得扩散到附图和详情图；适用于所有图片的规则始终遵守。"
    "出图前在本次响应内自检：主信息是否一眼可见、图形是否解释事实、商品是否需要出场、"
    "与相邻图片是否有合理变化。不要输出额外评审字段。\n\n"

    "【通用创意模板】\n"
    "styleLibrary 是版本化的通用模板目录。优先使用 taskOutline.styleTemplateId 选择的模板，"
    "读取所选模板的 guidance、pitfalls 和 promptTemplate，并结合任务书的风格与场景标签；"
    "没有已选模板时，按输出类型、视觉风格、场景和相近案例的顺序选择。"
    "模板是构图与表达方法，不是固定画面，不要把所有商品都做成同一种场景。"
    "将 taskOutline.bigIdea 与 visualMechanism 转成可见的主体动作、物体关系和视觉证据；"
    "没有创意卡时，根据本图任务和已确认事实自行确定一个主关系。"
    "禁止只用科技感、光带、粒子或渐变充当创意。"
    "辅助图形必须解释卖点；不能用概念图形冒充真实内部结构、实验结果或认证。\n\n"
    "模板正文中的品牌、商品、价格、数值和文案仅为例子，必须替换为当前商品已确认资料。"
    "案例编号只代表来源索引，未提供其图片或正文时不能声称已看过或照抄其构图。\n\n"

    "【visibleFacts】\n"
    "只写源图中确实可见的事实，逐项列出，每条不超过 30 字。"
    "商品本体可见时必须包含品牌标识（logo）的外观与位置；若 productPresence 为 none，禁止凭空补画 logo。\n\n"

    "【unconfirmedItems】\n"
    "写成简短的否定式短句，每条不超过 20 字，例如「不表现灯光效果」「不标注参数数值」。"
    "只写「不要画什么」，禁止写资料冲突、来源说明或推理过程。\n\n"

    "【exactCopy】\n"
    "只列本模块允许出现的文案原文，逐字给出；为空表示本图不出现文字。\n"
    "输入中的「模块参数」可能已包含用户提供的事实性文案（规格、卖点、参数），"
    "必须原样放进 exactCopy。\n"
    "事实性文案不足、且本模块允许出现文字时，可以补充表达性文案，但必须遵守：\n"
    "  · 不得包含任何数字、单位、规格、型号、容量、尺寸\n"
    "  · 不得包含功效、认证、销量、价格、折扣、排名、人群适用性\n"
    "  · 单条不超过 12 字，适合画面排版\n"
    "  · 每张图最多补充 2 条；宁可少写，不要凑数\n"
    "补充的表达性文案必须在开头加前缀「（生成）」。\n"
    "imagePrompt 必须逐字写出 exactCopy 中实际要上图的每条文字及其位置，"
    "不能只写『七条标签』或『显示上述参数』；图片模型只接收 imagePrompt，不会读取 exactCopy。"
    "『（生成）』是界面说明前缀，不是上图文字，写入 imagePrompt 时去掉该前缀。\n"
    "若约束声明本模块不允许出现文字，exactCopy 必须为空数组，imagePrompt 里也不写任何文字。\n\n"

    "【真实性红线】\n"
    "不得把不可见、无法可靠判断或用户未提供的信息写成事实。"
    "任务书中的构图建议也须核对源图，不能将建议当成商品事实。"
    "已知部件总数不代表已知每个部件的位置、名称和功能，不得为凑数补造隐藏结构或虚构视角；"
    "可用已确认的总数文案配合可见局部表达。"
    "品牌名称未知时仍须保留源图可见标识的形状与位置，不猜文字，也不擅自删改 logo。"
    "不得输出、改写或删除约束内容。\n\n"

    "【禁止事项】\n"
    "不要返回 taskPrompt 或任何未声明的字段。"
    "不要编造参数、认证、功效、销量、价格、折扣、材质等级、尺寸、容量、成分、产地与质保。\n"
)


_BOUNDED_ITEM = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


_BUILTIN_STYLE_SEEDS = {
    # 每条四要素：配色关系 | 光线特征 | 环境语汇范围 | 边界与禁忌
    # 配色只定「关系」不定「值」；环境只给「范围」不给「场景」；禁忌写真实失败模式。
    "minimal": (
        "以大面积留白和中性色为主，全画面主色不超过两种；均匀柔光、低对比、几乎无硬阴影；"
        "环境语汇限于无缝纯色背景与极简台面；禁止堆砌道具、装饰性特效、高饱和撞色，"
        "禁止为了填满画面而添加无关元素。"
    ),
    "studio": (
        "中性灰白影调，商品固有色准确、不受环境染色；标准影棚布光，主光加轮廓光，"
        "高光与阴影过渡可控；环境语汇限于无缝影棚背景与浅色台面；"
        "禁止彩色环境光污染商品色，禁止过曝高光与死黑阴影，禁止漂浮的接触面。"
    ),
    "editorial": (
        "低饱和高级灰配一到两个品牌色；柔和侧光与大面积暗部，层次细腻；"
        "环境语汇限于纸质纹理、精致网格与克制的陈列台；"
        "禁止信息堆砌、廉价渐变、过度修图的塑料感，禁止版式与品牌调性不符的装饰。"
    ),
    "precision": (
        "冷灰与深蓝为基调，少量蓝灰用于环境，不改变商品固有色；侧向条形柔光勾勒边缘，"
        "暗部保留层次；环境语汇限于规则网格、清晰水平垂直线与浅灰或深石墨背景；"
        "禁止把冷调环境染到商品本体上，禁止凭空增加刻度、仪表读数与透视内部结构。"
    ),
    "future": (
        "深蓝主背景配冷白主体光，冰蓝光带点缀，三者保持稳定比例；边缘轮廓光与体积光，"
        "高对比但主体曝光准确；环境语汇限于科技感渐变空间与几何结构；"
        "禁止全画面泛蓝，禁止霓虹色覆盖商品固有颜色，禁止发光元素抢过商品主体。"
    ),
    "industrial": (
        "低饱和灰黑与混凝土色，单一金属色点缀；硬朗定向光形成明确几何阴影；"
        "环境语汇限于金属、混凝土、格栅等结构感材质；"
        "禁止圆润柔美的装饰元素、糖果色，禁止把工业风做成脏乱或锈蚀感。"
    ),
    "warm-home": (
        "暖白与浅木色为主，点缀柔和绿植色；自然日光从侧面进入，暖调低对比，"
        "保留生活化的光影不均；环境语汇限于布艺、木纹、棉麻等真实家居材质；"
        "禁止冷光，禁止过度整洁的样板间感，禁止不符合居家尺度的夸张道具。"
    ),
    "nordic": (
        "浅木色与柔白色，少量低饱和灰蓝；通透高调日光，阴影淡而干净；"
        "环境语汇限于浅色木质表面、亚麻织物与简洁器物；"
        "禁止厚重暗调、深色背景、繁复纹样，禁止冷硬的人造光。"
    ),
    "urban-desk": (
        "中性灰白配一点深色，整体低饱和；清爽定向光，桌面有自然反射但不过曝；"
        "环境语汇限于现代办公桌面、键盘、笔记本等秩序化元素；"
        "禁止杂乱堆物、暖黄光，禁止出现可辨识的其他品牌标识。"
    ),
    "botanical": (
        "清透自然色，绿意作为点缀色而非主色；斑驳植物投影，柔和扩散光；"
        "环境语汇限于木质台面、陶土器皿与新鲜叶片；"
        "禁止人工塑料绿植、过饱和的荧光绿，禁止叶片遮挡商品主体结构。"
    ),
    "outdoor": (
        "自然饱和度，天空与植被色作背景；开阔日光，可有轻微逆光与真实阴影；"
        "环境语汇限于草地、石面、户外器械等真实户外环境；"
        "禁止棚拍感、过度调色的滤镜味，禁止出现无法确认的户外装备。"
    ),
    "eco": (
        "大地色系与再生纸色，低饱和不加亮色；朴素自然光，弱对比，保留材质的不完美；"
        "环境语汇限于再生纸、牛皮纸、未上漆木材等可持续材质；"
        "禁止镀金、亮面塑料、奢华装饰，禁止使用环保认证类标识。"
    ),
    "dark-luxury": (
        "深色为主，少量金属色点缀，主色不超过两种；低调定向光，高光精致克制，"
        "大面积暗部有层次；环境语汇限于深色石材、皮革、天鹅绒等厚重材质；"
        "禁止亮色撞色、廉价的镜面反光，禁止暗部死黑丢失商品轮廓。"
    ),
    "jewelry": (
        "中性深色或纯净背景，突出商品本身的金属与宝石色；精准轮廓光与点状高光，"
        "反射干净不含环境杂物；环境语汇限于细腻绒面或镜面台座；"
        "禁止把商品反射成环境色，禁止过度锐化，禁止凭空增加宝石与刻字。"
    ),
    "gallery": (
        "中性色域与大面积同色背景，商品是唯一色彩来源；聚焦式聚光灯，边缘自然衰减；"
        "环境语汇限于雕塑式展台、无缝墙面与克制的空间纵深；"
        "禁止装饰性道具、无意义的空间元素，禁止展厅感盖过商品本身。"
    ),
    "street": (
        "中性色打底，用一种高饱和亮色点缀；明亮日光或克制直闪，保留自然材质与肤质；"
        "环境语汇限于简洁街墙、路面、建筑边缘等城市元素；"
        "禁止密集涂鸦占满背景，禁止造成结构变形的超广角，禁止街头标志与名人形象。"
    ),
    "pop": (
        "高饱和撞色，主色与对比色关系明确，不超过三色；硬光形成清晰色块边界和明确投影；"
        "环境语汇限于几何图形与纯色背景；"
        "禁止色块压过商品主体，禁止色彩溢出到商品固有色上，禁止乱码文字装饰。"
    ),
    "retro": (
        "暖黄复古色调，颗粒感与轻微褪色；柔和老镜头感光线，暗角自然；"
        "环境语汇限于复古家具、老式物件与怀旧包装语汇；"
        "禁止现代冷光、过度锐化的高清感，禁止出现无法确认的年代标识与品牌。"
    ),
    "business": (
        "深灰、藏蓝与白，低饱和、高可信度；均匀专业布光，无戏剧化阴影；"
        "环境语汇限于现代办公或商务场景，线条简洁；"
        "禁止花哨装饰、活泼配色、休闲元素，禁止出现可辨识的第三方企业标识。"
    ),
    "family": (
        "柔和暖色与低饱和，无刺眼高饱和色；自然生活光，允许柔和的不均匀光照；"
        "环境语汇限于家居环境、软性材质与真实生活痕迹；"
        "禁止冷硬布光、过度修饰的完美感，禁止出现可辨识的真实儿童面孔。"
    ),
    "creator": (
        "自然真实色彩，可有轻微手机镜头的色偏；生活化自然光或补光灯效果，允许轻微过曝；"
        "环境语汇限于日常桌面、手持视角与真实使用痕迹；"
        "禁止影棚级的完美感、过度磨皮，禁止编造使用效果与人群适用性。"
    ),
}


class ModulePlanningV2Result(BaseModel):
    """模块规划结果：直接产出可用的生图提示词，不再由代码拼接结构化字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # 主产出：可直接交给图片模型的画面描述
    imagePrompt: str = Field(min_length=1, max_length=1200)
    # 供确认界面展示：本模块的文案摘要与画面说明（不进最终提示词）
    copySummary: str = Field(default="", max_length=500)
    visualDirection: str = Field(default="", max_length=1000)
    # 供确认界面展示：源图中确实可见的事实
    visibleFacts: list[_BOUNDED_ITEM] = Field(default_factory=list, max_length=50)
    # 供确认界面展示，并作为负向约束进入最终提示词
    unconfirmedItems: list[_BOUNDED_ITEM] = Field(default_factory=list, max_length=50)
    # 画面中允许出现的文案，逐字给出；为空表示本图不出现文字
    exactCopy: list[_BOUNDED_ITEM] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class StyleSeed:
    seed_id: str
    style_id: str
    version: str
    text: str
    sha256: str
    prompt_template_id: str | None = None
    prompt_version_id: str | None = None
    prompt_version_no: int | None = None
    prompt_content_sha256: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "seedId": self.seed_id,
            "styleId": self.style_id,
            "version": self.version,
            "text": self.text,
            "sha256": self.sha256,
            **({"promptTemplateId": self.prompt_template_id, "promptVersionId": self.prompt_version_id,
                "versionNo": self.prompt_version_no, "contentSha256": self.prompt_content_sha256}
               if self.prompt_version_id else {}),
        }


def resolve_style_seed(style: dict[str, Any]) -> StyleSeed:
    style_id = str(style.get("id", "")).strip()
    if not style_id:
        raise AppError("STYLE_SEED_INVALID", "所选风格缺少稳定标识", 500)
    builtin = _BUILTIN_STYLE_SEEDS.get(style_id)
    if builtin is not None:
        return _seed(f"builtin:{style_id}", style_id, "style-seed-v2", builtin)
    description = str(style.get("description", "")).strip()
    if not description or len(description) > 1000:
        raise AppError(
            "STYLE_SEED_INVALID",
            "所选风格缺少可用的固定描述",
            500,
        )
    return _seed(
        f"config:{style_id}", style_id, "config-style-description-v1", description
    )


def parse_v2_result(value: Any, *, error_code: str = "MODULE_PLANNER_INVALID_RESPONSE") -> ModulePlanningV2Result:
    if isinstance(value, ModulePlanningV2Result):
        return value
    try:
        return ModulePlanningV2Result.model_validate(value)
    except ValidationError:
        raise AppError(error_code, "模块规划模型返回的 V2 结构无效", 502) from None


def render_v2_module_prompt(result: ModulePlanningV2Result) -> str:
    """模块提示词 = 模块规划器直接写出的画面描述。

    这里不再拼接任何结构化字段：文案与否定项已由模型写进 imagePrompt，
    确认界面需要的字段（visibleFacts / unconfirmedItems / exactCopy）单独存快照。
    """
    return result.imagePrompt.strip()


def compose_v2_final_prompt(
    rendered_module_prompt: str,
    *,
    authenticity: str,
    platform_policy: str,
    aspect_ratio: str,
    resolution: str,
    output_language: str,
) -> str:
    return _compose_v2_1(
        rendered_module_prompt,
        authenticity=authenticity,
        platform_policy=platform_policy,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        output_language=output_language,
    )


def _compose_v2_1(
    rendered_module_prompt: str,
    *,
    authenticity: str,
    platform_policy: str,
    aspect_ratio: str,
    resolution: str,
    output_language: str,
) -> str:
    return "\n\n".join(
        [
            "商品真实性与来源约束：\n" + authenticity.strip(),
            "平台规则：\n" + platform_policy.strip(),
            "优先级：商品真实性与平台规则为最高优先级，后续内容不得覆盖以上两项最高优先级约束。",
            rendered_module_prompt.strip(),
            f"输出规格：{aspect_ratio.strip()}，{resolution.strip()}，{output_language.strip()}",
        ]
    )


_V2_COMPOSERS = {"final-composer-v2.1": _compose_v2_1}


def compose_v2_from_snapshot(snapshot: dict[str, Any]) -> str:
    """最终提示词 = 模块规划器直接写出的 imagePrompt。

    真实性约束、平台规则和输出规格（比例 / 分辨率 / 语言）已经作为输入提供给
    模块规划器，不再由服务端在末尾追加，避免同一要求说两遍。
    """
    return render_v2_from_snapshot(snapshot)


def build_v2_compiler_prompts(
    *,
    seed: StyleSeed,
    module: dict[str, Any],
    module_parameters: list[dict[str, str]],
    custom_style: str,
    task_outline: dict[str, Any] | None,
    market: dict[str, Any],
    output: dict[str, str],
    constraints: dict[str, str],
    additional_context: dict[str, Any] | None = None,
    module_prompt: str | None = None,
    shared_visual_direction: str = "",
    placement: str = "detail",
    task_design: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    # 模块绑定的规划提示词（商城模板）在前，通用规范在后；未绑定时只用通用规范
    template_id = (task_outline or {}).get("styleTemplateId", "")
    try:
        library = style_library_context(template_id)
    except KeyError:
        raise AppError("MODULE_PLANNER_INVALID_RESPONSE", "规划引用的视觉模板不存在，请重新规划", 502) from None
    bound = (module_prompt or "").strip()
    system_prompt = (f"【模块表达建议，可在任务目标内调整】\n{bound}\n\n{SYSTEM_PROMPT_BASE}"
                     if bound else SYSTEM_PROMPT_BASE)
    guides = task_outline.get("designGuideIds") if task_outline else ["visual-hierarchy"]
    if task_outline and not guides:
        raise AppError("MODULE_PLAN_NOT_READY", "请重新规划后生成图片", 409)
    commerce = commerce_design_context(guides)
    effective_outline, explicit_design = resolve_task_design(task_outline, task_design)
    explicit_composition = [p["value"] for p in module_parameters if p["key"] == "构图要求"]
    content_parameters = [p for p in module_parameters if p["key"] != "构图要求"]
    if placement not in {"primary", "gallery", "detail"}:
        raise AppError("MODULE_PLANNER_INVALID_INPUT", "图片展示位置无效", 400)
    reverse_guidance = (additional_context or {}).get("additionalContext", {})
    if reverse_guidance.get("reversePlanning") or reverse_guidance.get("reverseReference"):
        system_prompt += (
            "\nReverse references are design guidance, not current product facts. "
            "Current product evidence, platform constraints and selected style remain mandatory. "
            "When present, the selected overall reverse plan (additionalContext.reversePlanning) "
            "governs shared visual rules and content strategy for every module. "
            "Local reverseReference guidance may contribute layout and detail, including from "
            "a different version, but must adapt to the overall reverse plan rather than override it."
        )
    context = {
        "plannerVersion": PLANNER_VERSION_V2,
        "styleSeed": seed.to_snapshot(),
        "customStyle": normalize_custom_style(custom_style),
        "module": module,
        "moduleParameters": content_parameters,
        "commerceDesign": commerce,
        "sharedVisualDirection": shared_visual_direction,
        "placement": placement,
        "compositionAdvice": (task_outline or {}).get("compositionBrief", ""),
        "explicitCompositionRequirements": explicit_composition,
        "taskOutline": effective_outline,
        "explicitTaskDesign": explicit_design,
        "market": market,
        "output": output,
        "constraints": constraints,
        "designKnowledge": design_knowledge_context(load_design_knowledge()),
        "styleLibrary": library,
        "outputSchema": ModulePlanningV2Result.model_json_schema(),
        **(additional_context or {}),
    }
    user_prompt = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return system_prompt, user_prompt, {
        "requestVersion": PLANNER_VERSION_V2,
        "taskDesign": explicit_design,
        "effectiveTaskOutline": effective_outline,
        "commerceDesign": commerce,
        "styleLibraryVersion": library["version"],
        "styleLibraryRevision": library["revision"],
        "styleLibrarySha256": library["contentSha256"],
        "styleTemplateId": template_id,
        "systemPromptSha256": sha256(system_prompt.encode("utf-8")).hexdigest(),
        "userPromptSha256": sha256(user_prompt.encode("utf-8")).hexdigest(),
    }


def freeze_v2_module_planning(
    result: ModulePlanningV2Result,
    rendered_prompt: str,
) -> dict[str, Any]:
    payload = result.model_dump()
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "result": payload,
        "resultSha256": sha256(canonical.encode("utf-8")).hexdigest(),
        "rendererVersion": V2_RENDERER_VERSION,
        "composerVersion": V2_COMPOSER_VERSION,
        "renderedPrompt": rendered_prompt,
        "renderedPromptSha256": sha256(rendered_prompt.encode("utf-8")).hexdigest(),
    }


def normalize_custom_style(value: str) -> str:
    normalized = str(value).strip()
    if len(normalized) > 2000:
        raise AppError("CUSTOM_STYLE_INVALID", "补充风格说明不能超过 2000 个字符", 400)
    return normalized


def task_outline_from_master(master_snapshot: Any, task_id: str, module_id: str) -> dict[str, Any] | None:
    if not isinstance(master_snapshot, dict):
        return None
    modules = master_snapshot.get("modules")
    if not isinstance(modules, list):
        return None
    for item in modules:
        if not isinstance(item, dict):
            continue
        item_task_id = str(item.get("taskId") or item.get("moduleId") or "")
        if item_task_id == task_id or (
            item.get("taskId") is None and str(item.get("moduleId") or "") == module_id
        ):
            return json.loads(json.dumps(item, ensure_ascii=False))
    return None


def render_v2_from_snapshot(snapshot: dict[str, Any]) -> str:
    try:
        planning = snapshot["modulePlanning"]
        rendered = str(planning["renderedPrompt"])
        payload = parse_v2_result(
            planning["result"], error_code="MODULE_PLANNING_SNAPSHOT_INVALID"
        ).model_dump()
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if sha256(canonical.encode("utf-8")).hexdigest() != planning["resultSha256"]:
            raise ValueError("module planning result hash mismatch")
        if sha256(rendered.encode("utf-8")).hexdigest() != planning["renderedPromptSha256"]:
            raise ValueError("module planning snapshot hash mismatch")
        return rendered
    except AppError:
        raise
    except (KeyError, TypeError, ValueError):
        raise AppError(
            "MODULE_PLANNING_SNAPSHOT_INVALID", "V2 模块规划快照不完整或已损坏", 500
        ) from None


def _seed(seed_id: str, style_id: str, version: str, text: str) -> StyleSeed:
    return StyleSeed(seed_id, style_id, version, text, sha256(text.encode("utf-8")).hexdigest())
