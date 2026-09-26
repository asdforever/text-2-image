import asyncio
from pathlib import Path

import httpx

from backend.app.main import create_app
from backend.app.core.config import Settings
from backend.app.prompt_repository import MemoryPromptRepository


async def api(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(prompt_repository=MemoryPromptRepository())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_prompt_api_groups_versions_and_creates_from_history(tmp_path: Path) -> None:
    asyncio.run(_test_prompt_api_groups_versions_and_creates_from_history(tmp_path))


async def _test_prompt_api_groups_versions_and_creates_from_history(tmp_path: Path) -> None:
    async with await api(tmp_path) as client:
        created = await client.post("/api/prompt-templates", json={"code": "demo.prompt", "name": "Demo", "kind": "planner", "stage": "plan", "executionTarget": "llm", "body": "v1"})
        assert created.status_code == 201
        template_id = created.json()["data"]["template"]["id"]
        v1 = created.json()["data"]["version"]["id"]
        second = await client.post(f"/api/prompt-templates/{template_id}/versions", json={"baseVersionId": v1, "body": "v2", "changeNote": "revise"})
        assert second.status_code == 201
        listing = await client.get("/api/prompt-templates")
        assert listing.status_code == 200
        assert len(listing.json()["data"]) == 1
        assert listing.json()["data"][0]["versionCount"] == 2
        history = await client.get(f"/api/prompt-templates/{template_id}/versions")
        assert [item["versionNo"] for item in history.json()["data"]] == [1, 2]
        resolved = await client.get(f"/api/prompt-templates/{template_id}/resolve")
        assert resolved.json()["data"]["versionNo"] == 2
        historical = await client.get(f"/api/prompt-templates/{template_id}/resolve?versionId={v1}")
        assert historical.json()["data"]["versionNo"] == 1


def test_prompt_api_rejects_cross_template_version(tmp_path: Path) -> None:
    asyncio.run(_test_prompt_api_rejects_cross_template_version(tmp_path))


async def _test_prompt_api_rejects_cross_template_version(tmp_path: Path) -> None:
    async with await api(tmp_path) as client:
        first = await client.post("/api/prompt-templates", json={"code": "one", "name": "One", "kind": "planner", "stage": "plan", "executionTarget": "llm", "body": "one"})
        second = await client.post("/api/prompt-templates", json={"code": "two", "name": "Two", "kind": "planner", "stage": "plan", "executionTarget": "llm", "body": "two"})
        template_id = first.json()["data"]["template"]["id"]
        foreign_version = second.json()["data"]["version"]["id"]
        response = await client.post(f"/api/prompt-templates/{template_id}/versions", json={"baseVersionId": foreign_version, "body": "bad"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROMPT_VERSION_OWNERSHIP"


def test_prompt_list_batches_reads_and_preserves_template_views(monkeypatch) -> None:
    async def run() -> None:
        repository = MemoryPromptRepository()
        category = await repository.create_category("Shared category")
        beta, _ = await repository.create_template_with_version(
            code="beta", name="Beta", kind="planner", kind_name="Planning",
            execution_target="llm", body="beta", category_id=category.id,
        )
        alpha, first = await repository.create_template_with_version(
            code="alpha", name="Alpha", kind="planner", kind_name="Planning",
            execution_target="llm", body="first", category_id=category.id,
            input_schema=[{"name": "product"}], applicability={"scene": "hero"},
        )
        await repository.create_version(alpha, body="second")
        alpha.default_version_id = first.id
        beta.default_version_id = None
        empty = await repository.create_template(
            code="empty", name="Empty", kind="planner", kind_name="Planning",
            execution_target="llm",
        )
        # A foreign default must not be resolved from another template's batch.
        empty.default_version_id = first.id
        other, _ = await repository.create_template_with_version(
            code="other", name="Other stage", kind="planner", kind_name="Planning",
            execution_target="llm", body="other", stage="task_image",
        )

        async def forbid_individual_read(*_args):
            raise AssertionError("template lists must not read versions or categories per template")

        monkeypatch.setattr(repository, "list_versions", forbid_individual_read)
        monkeypatch.setattr(repository, "get_category", forbid_individual_read)
        app = create_app(Settings(database_url=None), prompt_repository=repository)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            response = await client.get("/api/prompt-templates?stage=plan")
            assert response.status_code == 200
            items = response.json()["data"]
            assert [item["name"] for item in items] == ["Alpha", "Beta", "Empty"]
            assert [item["versionCount"] for item in items] == [2, 1, 0]
            assert [item["categoryName"] for item in items] == ["Shared category", "Shared category", None]
            assert set(items[0]) == {
                "id", "code", "name", "kind", "kindName", "stage", "executionTarget",
                "defaultVersionId", "defaultVersion", "versionCount", "createdAt", "updatedAt",
                "templateId", "templateVersionId", "versionNo", "inputSchema", "applicability",
                "categoryId", "categoryName",
            }
            assert items[0]["defaultVersion"]["id"] == str(first.id)
            assert items[0]["defaultVersion"]["body"] == "first"
            assert items[0]["templateVersionId"] == str(first.id)
            assert items[0]["versionNo"] == 1
            assert items[0]["inputSchema"] == [{"name": "product"}]
            assert items[0]["applicability"] == {"scene": "hero"}
            for item in items[1:]:
                assert item["defaultVersion"] is None
                assert item["templateVersionId"] == ""
                assert item["versionNo"] == 0
                assert item["inputSchema"] == []
                assert item["applicability"] == {}
            assert items[2]["defaultVersionId"] == str(first.id)

            unfiltered = await client.get("/api/prompt-templates")
            assert [item["id"] for item in unfiltered.json()["data"]] == [
                str(alpha.id), str(beta.id), str(empty.id), str(other.id),
            ]
            missing_stage = await client.get("/api/prompt-templates?stage=missing")
            assert missing_stage.json()["data"] == []

    asyncio.run(run())
