import asyncio
from uuid import uuid4

from backend.app.generation_config_repository import InMemoryGenerationConfigRepository


def test_generation_config_repository_scopes_versions_to_workspace_and_increments() -> None:
    asyncio.run(_test_generation_config_repository_scopes_versions_to_workspace_and_increments())


async def _test_generation_config_repository_scopes_versions_to_workspace_and_increments() -> None:
    repository = InMemoryGenerationConfigRepository()
    workspace_id = uuid4()
    other_workspace_id = uuid4()

    first = await repository.publish(workspace_id, {"markets": [{"id": "taobao"}]})
    second = await repository.publish(workspace_id, {"markets": [{"id": "jd"}]})
    await repository.publish(other_workspace_id, {"markets": [{"id": "amazon"}]})

    assert (first.version_no, second.version_no) == (1, 2)
    assert await repository.get_current(other_workspace_id) is not second
    assert [item.version_no for item in await repository.list_versions(workspace_id)] == [1, 2]
    assert await repository.get_version(workspace_id, 3) is None


def test_generation_config_repository_preserves_published_history_and_returns_copies() -> None:
    asyncio.run(_test_generation_config_repository_preserves_published_history_and_returns_copies())


async def _test_generation_config_repository_preserves_published_history_and_returns_copies() -> None:
    repository = InMemoryGenerationConfigRepository()
    workspace_id = uuid4()
    document = {"markets": [{"id": "taobao", "labels": ["淘宝"]}]}

    published = await repository.publish(workspace_id, document)
    document["markets"][0]["id"] = "changed-by-caller"
    current = await repository.get_current(workspace_id)
    assert current is not None
    current.content["markets"][0]["id"] = "changed-by-reader"

    historical = await repository.get_version(workspace_id, published.version_no)
    assert historical is not None
    assert historical.content == {"markets": [{"id": "taobao", "labels": ["淘宝"]}]}
    assert historical.content_sha256 == "f302ada9c40f97a804f19ddb1b12177a2d35c965ff4dad09ca5cdaa0e6ffbf30"
