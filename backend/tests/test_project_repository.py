import asyncio
from uuid import uuid4

from backend.app.project_repository import InMemoryProjectRepository


def test_project_repository_filters_active_projects_by_workspace() -> None:
    asyncio.run(_test_project_repository_filters_active_projects_by_workspace())


async def _test_project_repository_filters_active_projects_by_workspace() -> None:
    repository = InMemoryProjectRepository()
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    active = await repository.create_project("主图项目", workspace_id)
    archived = await repository.create_project("归档项目", workspace_id)
    await repository.create_project("其他项目", other_workspace_id)
    await repository.archive_project(archived.id, workspace_id)

    assert [item.id for item in await repository.list_projects(workspace_id)] == [active.id]
    assert {item.id for item in await repository.list_projects(workspace_id, include_archived=True)} == {
        active.id,
        archived.id,
    }
    assert await repository.get_project(active.id, other_workspace_id) is None


def test_project_repository_keeps_shared_object_until_all_assets_are_removed() -> None:
    asyncio.run(_test_project_repository_keeps_shared_object_until_all_assets_are_removed())


async def _test_project_repository_keeps_shared_object_until_all_assets_are_removed() -> None:
    repository = InMemoryProjectRepository()
    workspace_id = uuid4()
    first = await repository.create_project("项目一", workspace_id)
    second = await repository.create_project("项目二", workspace_id)
    object_record = await repository.create_object(
        workspace_id,
        "projects/shared/source.png",
        "source.png",
        "image/png",
        128,
        16,
        9,
        "a" * 64,
    )
    first_asset = await repository.create_asset(first.id, object_record.id, "source")
    second_asset = await repository.create_asset(second.id, object_record.id, "source")

    assert await repository.object_reference_count(object_record.id) == 2
    await repository.delete_asset(first_asset.id, workspace_id)
    assert await repository.object_reference_count(object_record.id) == 1
    assert await repository.get_asset(second_asset.id, workspace_id) is not None


def test_project_repository_reuses_persisted_state_across_application_instances() -> None:
    asyncio.run(_test_project_repository_reuses_persisted_state_across_application_instances())


async def _test_project_repository_reuses_persisted_state_across_application_instances() -> None:
    workspace_id = uuid4()
    backing_store = {}
    first_instance = InMemoryProjectRepository(backing_store)
    created = await first_instance.create_project("持久化项目", workspace_id)

    second_instance = InMemoryProjectRepository(backing_store)
    restored = await second_instance.get_project(created.id, workspace_id)

    assert restored is not None
    assert restored.name == "持久化项目"
