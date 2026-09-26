from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .core.errors import AppError


DEFAULT_MARKETS = [
    {"id": "taobao", "label": "淘宝", "marketScope": "domestic", "platforms": "淘宝", "guidance": "主图优先白底，突出商品主体，避免夸大功效描述。", "defaultLanguage": "中文"},
    {"id": "tmall", "label": "天猫", "marketScope": "domestic", "platforms": "天猫", "guidance": "保持品牌视觉统一，使用清晰的卖点和规范化商品信息。", "defaultLanguage": "中文"},
    {"id": "jd", "label": "京东", "marketScope": "domestic", "platforms": "京东", "guidance": "主图使用干净背景，准确呈现产品颜色、结构与规格。", "defaultLanguage": "中文"},
    {"id": "pdd", "label": "拼多多", "marketScope": "domestic", "platforms": "拼多多", "guidance": "画面信息直接易读，突出核心商品与性价比事实。", "defaultLanguage": "中文"},
    {"id": "douyin", "label": "抖音小店", "marketScope": "domestic", "platforms": "抖音小店", "guidance": "适合移动端浏览，使用真实场景和简洁卖点表达。", "defaultLanguage": "中文"},
    {"id": "kuaishou", "label": "快手小店", "marketScope": "domestic", "platforms": "快手小店", "guidance": "保持真实生活化的场景表达，避免过度修饰。", "defaultLanguage": "中文"},
    {"id": "amazon", "label": "亚马逊", "marketScope": "overseas", "platforms": "Amazon", "guidance": "主图采用纯白背景，避免文字、道具和水印，准确展示产品。", "defaultLanguage": "英文"},
    {"id": "shopify", "label": "Shopify", "marketScope": "overseas", "platforms": "Shopify", "guidance": "按品牌视觉规范组织商品图，适配目标国家语言和法规。", "defaultLanguage": "英文"},
    {"id": "ebay", "label": "eBay", "marketScope": "overseas", "platforms": "eBay", "guidance": "清晰展示商品状态、配件和关键规格，避免误导性表达。", "defaultLanguage": "英文"},
    {"id": "walmart", "label": "Walmart", "marketScope": "overseas", "platforms": "Walmart", "guidance": "优先真实、清晰的产品展示，保持目录信息一致。", "defaultLanguage": "英文"},
]

DEFAULT_MODELS = [
    {"id": "gpt-image-2-5", "label": "GPT Image 2.5", "provider": "OpenAI", "constraints": "支持超清 4K 输出", "resolutions": ["标准 1K", "高清 2K", "超清 4K"]},
    {"id": "flux-pro", "label": "Flux Pro", "provider": "Black Forest Labs", "constraints": "当前最高支持高清 2K", "resolutions": ["标准 1K", "高清 2K"]},
]

DEFAULT_STYLE_CATEGORIES = [
    {"id": "basic", "label": "基础风格", "styles": [
        {"id": "minimal", "label": "极简商业", "description": "克制留白与清晰产品轮廓"},
        {"id": "studio", "label": "高级棚拍", "description": "柔和棚拍光线与真实质感"},
        {"id": "editorial", "label": "杂志编辑", "description": "精致排版与品牌叙事感"},
    ]},
    {"id": "digital", "label": "科技数码", "styles": [
        {"id": "precision", "label": "冷调精密", "description": "冷静背景与理性参数秩序"},
        {"id": "future", "label": "未来霓虹", "description": "光带层次与未来科技氛围"},
        {"id": "industrial", "label": "极简工业", "description": "金属结构与硬朗造型表达"},
    ]},
    {"id": "home", "label": "居家生活", "styles": [
        {"id": "warm-home", "label": "温暖居家", "description": "自然日光与舒适家庭氛围"},
        {"id": "nordic", "label": "北欧清爽", "description": "浅色木质与干净生活空间"},
        {"id": "urban-desk", "label": "都市办公", "description": "现代桌面与高效工作状态"},
    ]},
    {"id": "nature", "label": "自然清新", "styles": [
        {"id": "botanical", "label": "清新植感", "description": "植物光影与清透自然色彩"},
        {"id": "outdoor", "label": "户外轻盈", "description": "户外环境与自在使用体验"},
        {"id": "eco", "label": "环保叙事", "description": "再生材质与可持续生活表达"},
    ]},
    {"id": "premium", "label": "品质奢华", "styles": [
        {"id": "dark-luxury", "label": "深色奢华", "description": "深色材质与精致高光层次"},
        {"id": "jewelry", "label": "珠宝质感", "description": "细腻反射与珍贵材质氛围"},
        {"id": "gallery", "label": "艺术展陈", "description": "雕塑构图与高级陈列空间"},
    ]},
    {"id": "fashion", "label": "潮流文化", "styles": [
        {"id": "street", "label": "街头潮流", "description": "大胆色彩与年轻街头语境"},
        {"id": "pop", "label": "波普撞色", "description": "高饱和撞色与活力图形语言"},
        {"id": "retro", "label": "复古潮玩", "description": "复古色调与趣味潮玩表达"},
    ]},
    {"id": "people", "label": "人群主题", "styles": [
        {"id": "business", "label": "商务精英", "description": "专业环境与可靠效率表达"},
        {"id": "family", "label": "家庭亲子", "description": "亲密互动与安心使用氛围"},
        {"id": "creator", "label": "达人推荐", "description": "真实体验与内容创作语境"},
    ]},
]


def _module(module_id: str, label: str, description: str, mode: str) -> dict[str, str]:
    return {"id": module_id, "label": label, "description": description, "mode": mode}


HERO_MODULES = [
    _module("hero-kv", "首屏 KV", "建立第一眼识别与主卖点", "hero"),
    _module("hero-overview", "整体展示", "完整呈现产品形态与质感", "hero"),
    _module("hero-detail", "细节特写", "放大关键材质与工艺细节", "hero"),
    _module("hero-scene", "使用场景", "呈现产品在真实环境中的状态", "hero"),
    _module("hero-colors", "多色套装", "展示不同颜色或组合规格", "hero"),
    _module("hero-compare", "功能对比", "清晰说明功能与差异优势", "hero"),
    _module("hero-package", "包装展示", "呈现包装、配件与开箱内容", "hero"),
    _module("hero-benefit", "权益保障", "展示服务承诺与购买保障", "hero"),
]

SUITE_MODULES = [
    _module("suite-hero", "首屏主视觉", "传递核心价值并建立视觉基调", "suite"),
    _module("suite-benefit", "核心卖点图", "突出最具说服力的购买理由", "suite"),
    _module("suite-scene", "使用场景图", "呈现真实使用环境与状态", "suite"),
    _module("suite-angle", "多角度图", "从多个角度完整展示外观", "suite"),
    _module("suite-mood", "场景氛围图", "营造品牌与产品使用氛围", "suite"),
    _module("suite-detail", "商品细节图", "放大材质结构与关键工艺", "suite"),
    _module("suite-story", "品牌故事图", "传达品牌理念与产品缘起", "suite"),
    _module("suite-size", "尺寸/容量/尺码图", "展示规格尺寸与容量信息", "suite"),
    _module("suite-effect", "效果对比图", "直观呈现使用前后的差异", "suite"),
    _module("suite-spec", "详细规格/参数表", "集中展示详细产品参数", "suite"),
    _module("suite-craft", "工艺制作图", "展示生产过程与制作工艺", "suite"),
    _module("suite-accessory", "配件/赠品图", "明确包装内配件与赠品内容", "suite"),
    _module("suite-series", "系列展示图", "展示同系列型号与差异", "suite"),
    _module("suite-ingredient", "商品成分图", "清晰说明材料或成分构成", "suite"),
    _module("suite-support", "售后保障图", "说明质保退换与服务政策", "suite"),
    _module("suite-guide", "使用建议图", "讲清使用步骤与注意事项", "suite"),
    _module("suite-buyer", "买家秀", "呈现真实用户使用体验", "suite"),
    _module("suite-creator", "博主推荐图", "以达人视角传递推荐理由", "suite"),
]


def create_default_generation_config() -> dict[str, Any]:
    style_categories = deepcopy(DEFAULT_STYLE_CATEGORIES)
    return {
        "version": 1,
        "savedAt": datetime.fromtimestamp(0, timezone.utc).isoformat().replace("+00:00", "Z"),
        "markets": deepcopy(DEFAULT_MARKETS),
        "models": deepcopy(DEFAULT_MODELS),
        "promptModel": None,
        "styleCategories": style_categories,
        "heroModules": deepcopy(HERO_MODULES),
        "suiteModules": deepcopy(SUITE_MODULES),
        "marketBindings": {item["id"]: None for item in DEFAULT_MARKETS},
        "modelBindings": {item["id"]: None for item in DEFAULT_MODELS},
        "heroBindings": {item["id"]: None for item in HERO_MODULES},
        "suiteBindings": {item["id"]: None for item in SUITE_MODULES},
    }


def normalize_generation_config(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _invalid("配置必须为对象")
    config = deepcopy(value)
    markets = _normalize_markets(config.get("markets"))
    models = _normalize_models(config.get("models"))
    styles = _normalize_styles(config.get("styleCategories"))
    hero_modules = _normalize_modules(config.get("heroModules"), "hero", "主图模块")
    suite_modules = _normalize_modules(config.get("suiteModules"), "suite", "详情页模块")

    try:
        version = int(config.get("version", 1))
    except (TypeError, ValueError):
        _invalid("配置版本必须为正整数")
    if version < 1:
        _invalid("配置版本必须为正整数")

    normalized = {
        "version": version,
        "savedAt": str(config.get("savedAt", "")).strip(),
        "markets": markets,
        "models": models,
        "promptModel": _normalize_prompt_model(config.get("promptModel")),
        "styleCategories": styles,
        "heroModules": hero_modules,
        "suiteModules": suite_modules,
    }
    binding_specs = {
        "marketBindings": [item["id"] for item in markets],
        "heroBindings": [item["id"] for item in hero_modules],
        "suiteBindings": [item["id"] for item in suite_modules],
    }
    for field, ids in binding_specs.items():
        source = config.get(field, {})
        if not isinstance(source, dict):
            _invalid(f"{field} 必须为对象")
        normalized[field] = {item_id: deepcopy(source.get(item_id)) for item_id in ids}
    normalized["modelBindings"] = {item["id"]: None for item in models}
    return normalized


def _normalize_prompt_model(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"connectionId"}:
        _invalid("提示词模型只能包含连接标识，不能包含凭据")
    connection_id = value.get("connectionId")
    if not isinstance(connection_id, str) or not connection_id.strip() or len(connection_id) > 200:
        _invalid("请选择有效的提示词模型连接")
    return {"connectionId": connection_id.strip()}


def _normalize_markets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _invalid("至少需要一个具体电商平台")
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            _invalid("电商市场条目格式无效")
        item = {key: str(raw.get(key, "")).strip() for key in ("id", "label", "platforms", "guidance", "defaultLanguage")}
        item["marketScope"] = str(raw.get("marketScope", "")).strip()
        if item["id"] in {"domestic", "international", "overseas"}:
            _invalid("电商市场必须选择具体电商平台")
        if not all(item[key] for key in ("id", "label", "platforms", "guidance", "defaultLanguage")):
            _invalid("电商市场字段不能为空")
        if item["marketScope"] not in {"domestic", "overseas"}:
            _invalid("市场范围必须为国内或国外")
        result.append(item)
    _require_unique(result, "电商市场")
    return result


def _normalize_models(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _invalid("至少需要一个生图模型")
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            _invalid("生图模型条目格式无效")
        item = {key: str(raw.get(key, "")).strip() for key in ("id", "label", "provider", "constraints")}
        if "apiKey" in raw or "api_key" in raw:
            _invalid("API Key 请通过模型连接单独保存，不能写入普通生成配置")
        if raw.get("connectionId"):
            from uuid import UUID
            try:
                connection_id = str(raw["connectionId"])
                if connection_id != "environment":
                    UUID(connection_id)
                item["connectionId"] = connection_id
            except (ValueError, TypeError):
                _invalid("模型连接标识无效")
        if "aspectRatios" in raw:
            ratios = raw["aspectRatios"]
            if not isinstance(ratios, list) or any(not isinstance(ratio, str) or ratio not in {"1:1", "3:4", "4:3", "16:9"} for ratio in ratios):
                _invalid("模型比例只能选择当前支持的 1:1、3:4、4:3、16:9")
            item["aspectRatios"] = list(dict.fromkeys(ratios))
        resolutions = raw.get("resolutions")
        if not isinstance(resolutions, list):
            _invalid(f"模型“{item['label']}”至少支持一种分辨率")
        item["resolutions"] = list(dict.fromkeys(str(entry).strip() for entry in resolutions if str(entry).strip()))
        from .core.image_dimensions import RESOLUTION_LEVELS, normalize_resolution
        item["resolutions"] = list(dict.fromkeys(normalize_resolution(entry) for entry in item["resolutions"]))
        if any(entry not in RESOLUTION_LEVELS for entry in item["resolutions"]):
            _invalid("模型分辨率只能选择当前支持的 1K、2K、4K")
        if not item["id"] or not item["label"]:
            _invalid("生图模型必填字段不能为空")
        if not item["resolutions"]:
            _invalid(f"模型“{item['label']}”至少支持一种分辨率")
        result.append(item)
    _require_unique(result, "生图模型")
    return result


def _normalize_styles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _invalid("风格大类必须为数组")
    categories = []
    all_style_ids: set[str] = set()
    for raw_category in value:
        if not isinstance(raw_category, dict):
            _invalid("风格大类格式无效")
        category_id = str(raw_category.get("id", "")).strip()
        label = str(raw_category.get("label", "")).strip()
        raw_styles = raw_category.get("styles")
        if not category_id or not label or not isinstance(raw_styles, list):
            _invalid("风格大类必填字段不能为空")
        if len(raw_styles) > 4:
            _invalid(f"风格大类“{label}”最多 4 个风格")
        styles = []
        for raw_style in raw_styles:
            if not isinstance(raw_style, dict):
                _invalid("风格条目格式无效")
            style = {key: str(raw_style.get(key, "")).strip() for key in ("id", "label", "description")}
            if not all(style.values()):
                _invalid("风格必填字段不能为空")
            if style["id"] in all_style_ids:
                _invalid("风格标识不能重复")
            all_style_ids.add(style["id"])
            styles.append(style)
        _require_unique(styles, f"风格大类“{label}”中的风格")
        categories.append({"id": category_id, "label": label, "styles": styles})
    _require_unique(categories, "风格大类")
    return categories


def _normalize_modules(value: Any, mode: str, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        _invalid(f"至少需要一个{label}")
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            _invalid(f"{label}条目格式无效")
        item = {key: str(raw.get(key, "")).strip() for key in ("id", "label", "description", "mode")}
        if not item["id"] or not item["label"] or not item["description"]:
            _invalid(f"{label}必填字段不能为空")
        if item["mode"] != mode:
            _invalid(f"{label}类型必须为 {mode}")
        result.append(item)
    _require_unique(result, label)
    return result


def _require_unique(items: list[dict[str, Any]], label: str) -> None:
    ids = [item["id"] for item in items]
    labels = [item["label"].casefold() for item in items]
    if len(ids) != len(set(ids)):
        _invalid(f"{label}标识不能重复")
    if len(labels) != len(set(labels)):
        _invalid(f"{label}名称不能重复")


def _invalid(message: str) -> None:
    raise AppError("GENERATION_CONFIG_INVALID", message, 400)
