import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository, PromptRepositoryError


@pytest.mark.asyncio
async def test_memory_categories_normalize_names_and_assign_templates() -> None:
    repository = MemoryPromptRepository()
    category = await repository.create_category("  主图卖点  ")
    assert category.name == "主图卖点"

    template, _ = await repository.create_template_with_version(
        code="hero.sales",
        name="主图卖点",
        kind="text_to_image",
        kind_name="文生图",
        execution_target="image_model",
        body="system",
        category_id=category.id,
    )
    listed = await repository.list_templates()
    assert listed[0].category_id == category.id
    assert (await repository.get_category(category.id)).name == "主图卖点"


@pytest.mark.asyncio
async def test_prompt_templates_can_be_filtered_by_stage() -> None:
    repository = MemoryPromptRepository()
    await repository.create_template_with_version(
        code="base.refine", name="白底图", kind="text_to_image", kind_name="文生图",
        execution_target="image_model", body="system", stage="base_refine",
    )
    await repository.create_template_with_version(
        code="plan.main", name="主图规划", kind="text_to_text", kind_name="文生文",
        execution_target="llm", body="system", stage="plan",
    )

    listed = await repository.list_templates("base_refine")
    assert [item.code for item in listed] == ["base.refine"]


@pytest.mark.asyncio
async def test_memory_categories_reject_duplicates_and_uncategorize_on_delete() -> None:
    repository = MemoryPromptRepository()
    category = await repository.create_category("详情页")
    with pytest.raises(PromptRepositoryError, match="PROMPT_CATEGORY_CONFLICT"):
        await repository.create_category("  详情页 ")

    template, _ = await repository.create_template_with_version(
        code="suite.detail",
        name="详情规划",
        kind="text_to_text",
        kind_name="文生文",
        execution_target="llm",
        body="system",
        category_id=category.id,
    )
    assert await repository.count_templates_for_category(category.id) == 1
    deleted = await repository.delete_category(category.id)
    assert deleted == 1
    assert (await repository.get_template(template.id)).category_id is None


@pytest.mark.asyncio
async def test_memory_category_rename_preserves_id() -> None:
    repository = MemoryPromptRepository()
    category = await repository.create_category("旧名称")
    renamed = await repository.update_category(category.id, "新名称")
    assert renamed.id == category.id
    assert renamed.name == "新名称"


@pytest.mark.asyncio
async def test_category_routes_cover_lifecycle_and_template_assignment(tmp_path) -> None:
    app = create_app(
        Settings(environment="development"),
        prompt_repository=MemoryPromptRepository(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/prompt-categories", json={"name": "主图"})
        assert created.status_code == 201
        category = created.json()["data"]

        duplicate = await client.post("/api/prompt-categories", json={"name": " 主图 "})
        assert duplicate.status_code == 409

        prompt = await client.post("/api/prompt-templates", json={
            "code": "hero.category",
            "name": "分类主图",
            "kind": "text_to_image",
            "kindName": "文生图",
            "executionTarget": "image_model",
            "body": "system",
            "categoryId": category["id"],
        })
        assert prompt.status_code == 201
        assert prompt.json()["data"]["template"]["categoryId"] == category["id"]

        deleted = await client.delete(f"/api/prompt-categories/{category['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["affectedTemplateCount"] == 1
        listed = await client.get("/api/prompt-templates")
        assert listed.json()["data"][0]["categoryId"] is None
