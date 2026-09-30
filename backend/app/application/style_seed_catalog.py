"""Versioned marketplace source for built-in visual styles."""
from hashlib import sha256

from ..core.errors import AppError
from ..generation_config_catalog import DEFAULT_STYLE_CATEGORIES
from ..prompt_repository import PromptRepositoryError
from .module_planning_v2 import StyleSeed, resolve_style_seed


def style_template_code(style_id: str) -> str:
    return f"picagent.style-seed.{style_id}"


async def import_style_seeds(service) -> dict:
    """Add missing templates only; preserve all existing bodies, defaults and categories."""
    categories = await service.list_categories()
    category = next((item for item in categories if item.name == "风格库"), None)
    if category is None:
        try:
            category = await service.create_category("风格库")
        except PromptRepositoryError as error:
            if str(error) != "PROMPT_CATEGORY_CONFLICT":
                raise
            category = next(item for item in await service.list_categories() if item.name == "风格库")
    created, existing = [], []
    for group in DEFAULT_STYLE_CATEGORIES:
        for style in group["styles"]:
            code = style_template_code(style["id"])
            if await service.repository.get_template_by_code(code):
                existing.append(code)
                continue
            seed = resolve_style_seed(style)
            try:
                await service.create_template({
                    "code": code, "name": style["label"], "kind": "image_to_image", "kind_name": "风格种子",
                    "execution_target": "llm", "stage": "plan", "category_id": category.id,
                    "body": seed.text, "source": "builtin-style-seed-v2",
                    "change_note": "导入现有内置风格种子；新任务引用商城默认版本，历史任务保留冻结快照。",
                    "applicability": {"runtimeRole": "style-seed", "styleId": style["id"],
                                      "styleCategory": group["label"], "description": style["description"],
                                      "seedVersion": seed.version, "seedSha256": seed.sha256},
                }, idempotency_key=f"import:{code}:v1")
                created.append(code)
            except PromptRepositoryError as error:
                if str(error) != "PROMPT_CODE_CONFLICT":
                    raise
                existing.append(code)
    return {"created": created, "existing": existing}


async def resolve_marketplace_style_seed(style: dict, repository) -> StyleSeed:
    """Freeze the default version once per operation; older installations retain their fallback."""
    lookup = getattr(repository, "get_template_by_code", None)
    template = await lookup(style_template_code(str(style.get("id", "")))) if lookup else None
    if template is None:
        return resolve_style_seed(style)
    version = await repository.get_version(template.default_version_id) if template.default_version_id else None
    if version is None or version.template_id != template.id:
        raise AppError("STYLE_SEED_VERSION_INVALID", "商城风格缺少有效默认版本，请在提示词商城选择版本", 409)
    applicability = version.applicability or {}
    if applicability.get("runtimeRole") != "style-seed" or applicability.get("styleId") != style.get("id"):
        raise AppError("STYLE_SEED_VERSION_INVALID", "商城风格版本与所选风格不匹配", 409)
    if not isinstance(version.body, str) or not version.body.strip():
        raise AppError("STYLE_SEED_INVALID", "商城风格内容为空，请在提示词商城补充风格描述", 409)
    return StyleSeed(
        seed_id=f"prompt:{template.id}", style_id=style["id"], version=f"prompt-version:{version.version_no}",
        text=version.body, sha256=sha256(version.body.encode("utf-8")).hexdigest(),
        prompt_template_id=str(template.id), prompt_version_id=str(version.id),
        prompt_version_no=version.version_no, prompt_content_sha256=version.content_sha256,
    )
