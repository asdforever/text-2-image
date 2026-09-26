from uuid import UUID

import pytest

from backend.app.application.image_editing_service import ImageEditingService
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.project_repository import InMemoryProjectRepository


@pytest.mark.asyncio
async def test_create_image_edit_session_requires_project_scoped_source_version():
    workspace_id = UUID(int=11)
    other_workspace_id = UUID(int=12)
    projects = InMemoryProjectRepository()
    project = await projects.create_project("键盘项目", workspace_id)
    other_project = await projects.create_project("其他项目", workspace_id)
    other_workspace_project = await projects.create_project("其他工作区", other_workspace_id)
    source = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", 10, 16, 9, "a" * 64)
    source_asset = await projects.create_asset(project.id, source.id, "source")
    foreign_object = await projects.create_object(workspace_id, "foreign.png", "foreign.png", "image/png", 10, 16, 9, "b" * 64)
    foreign_asset = await projects.create_asset(other_project.id, foreign_object.id, "source")
    other_workspace_object = await projects.create_object(other_workspace_id, "other.png", "other.png", "image/png", 10, 16, 9, "c" * 64)
    other_workspace_asset = await projects.create_asset(other_workspace_project.id, other_workspace_object.id, "source")
    service = ImageEditingService(
        repository=None,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
    )

    session = await service.create_session(project.id, source_asset.id)

    assert session.project_id == project.id
    assert session.workspace_id == workspace_id
    assert session.source_version_id == source_asset.id
    assert session.revision == 1
    assert session.status == "draft"
    assert (await service.get_session(session.id)).id == session.id

    with pytest.raises(AppError, match="IMAGE_EDIT_SOURCE_SCOPE"):
        await service.create_session(project.id, foreign_asset.id)
    with pytest.raises(AppError, match="IMAGE_EDIT_SOURCE_SCOPE"):
        await service.create_session(project.id, other_workspace_asset.id)
    with pytest.raises(AppError, match="IMAGE_EDIT_PROJECT_NOT_FOUND"):
        await service.create_session(UUID(int=999), source_asset.id)


@pytest.mark.asyncio
async def test_get_image_edit_session_does_not_cross_workspace_boundary():
    workspace_id = UUID(int=21)
    projects = InMemoryProjectRepository()
    project = await projects.create_project("项目", workspace_id)
    source = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", 10, 16, 9, "d" * 64)
    source_asset = await projects.create_asset(project.id, source.id, "source")
    repository = None
    service = ImageEditingService(
        repository=repository,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
    )
    session = await service.create_session(project.id, source_asset.id)

    foreign_service = ImageEditingService(
        repository=service.repository,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=2), UUID(int=22), "owner")),
    )
    assert await foreign_service.get_session(session.id) is None


@pytest.mark.asyncio
async def test_image_edit_operations_use_optimistic_session_revision():
    workspace_id = UUID(int=31)
    projects = InMemoryProjectRepository()
    project = await projects.create_project("项目", workspace_id)
    source = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", 10, 16, 9, "e" * 64)
    source_asset = await projects.create_asset(project.id, source.id, "source")
    service = ImageEditingService(
        repository=None,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
    )
    session = await service.create_session(project.id, source_asset.id)

    saved = await service.add_operation(session.id, {"operationId": "op-1", "type": "inpaint", "payload": {"prompt": "更换背景"}}, expected_revision=1)
    assert saved.revision == 2
    assert saved.operations_snapshot[0]["type"] == "inpaint"

    with pytest.raises(AppError, match="IMAGE_EDIT_REVISION_CONFLICT"):
        await service.add_operation(session.id, {"operationId": "op-2", "type": "erase", "payload": {}}, expected_revision=1)
    latest = await service.get_session(session.id)
    assert latest.revision == 2
    assert len(latest.operations_snapshot) == 1

    updated = await service.update_operation(session.id, "op-1", {"type": "inpaint", "payload": {"prompt": "保留主体"}}, expected_revision=2)
    assert updated.revision == 3
    assert updated.operations_snapshot[0]["payload"]["prompt"] == "保留主体"
    removed = await service.remove_operation(session.id, "op-1", expected_revision=3)
    assert removed.revision == 4
    assert removed.operations_snapshot == []


@pytest.mark.asyncio
async def test_ocr_is_idempotent_and_isolated_by_source_version():
    workspace_id = UUID(int=41)
    projects = InMemoryProjectRepository()
    project = await projects.create_project("项目", workspace_id)
    first_object = await projects.create_object(workspace_id, "a.png", "a.png", "image/png", 10, 16, 9, "f" * 64)
    first = await projects.create_asset(project.id, first_object.id, "source")
    second_object = await projects.create_object(workspace_id, "b.png", "b.png", "image/png", 10, 16, 9, "0" * 64)
    second = await projects.create_asset(project.id, second_object.id, "source")

    class FakeOcr:
        def __init__(self):
            self.calls = 0
        async def recognize(self, source_snapshot):
            self.calls += 1
            return {"text": f"识别{source_snapshot['assetId']}", "regions": [{"text": "标题", "confidence": 0.99}]}

    provider = FakeOcr()
    service = ImageEditingService(
        repository=None,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        ocr_provider=provider,
    )
    session = await service.create_session(project.id, first.id)
    result1 = await service.recognize_ocr(session.id, first.id, idempotency_key="ocr-a")
    result2 = await service.recognize_ocr(session.id, first.id, idempotency_key="ocr-a")
    result3 = await service.recognize_ocr(session.id, second.id, idempotency_key="ocr-b")

    assert result1.id == result2.id
    assert result1.source_version_id == first.id
    assert result3.source_version_id == second.id
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_submit_image_edit_session_creates_queued_task_and_is_idempotently_replayed():
    workspace_id = UUID(int=51)
    projects = InMemoryProjectRepository()
    project = await projects.create_project("项目", workspace_id)
    source_object = await projects.create_object(workspace_id, "a.png", "a.png", "image/png", 10, 16, 9, "1" * 64)
    source = await projects.create_asset(project.id, source_object.id, "source")
    service = ImageEditingService(
        repository=None,
        project_repository=projects,
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
    )
    session = await service.create_session(project.id, source.id)

    with pytest.raises(AppError, match="IMAGE_EDIT_EMPTY_DRAFT"):
        await service.submit_session(session.id, prompt_snapshot={}, config_snapshot={})

    await service.add_operation(session.id, {"operationId": "op-1", "type": "erase", "payload": {}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "清除背景"}, config_snapshot={"model": "gpt-image-2"}, idempotency_key="submit-1")
    replay = await service.submit_session(session.id, prompt_snapshot={"summary": "清除背景"}, config_snapshot={"model": "gpt-image-2"}, idempotency_key="submit-1")

    assert task.id == replay.id
    assert task.status == "queued"
    assert task.operations_snapshot[0]["operationId"] == "op-1"
    assert task.prompt_snapshot["summary"] == "清除背景"
    assert task.attempts[0].status == "queued"


@pytest.mark.asyncio
async def test_archiving_edit_session_hides_it_but_keeps_history():
    workspace_id = UUID(int=52)
    projects = InMemoryProjectRepository(); project = await projects.create_project("项目", workspace_id)
    source_object = await projects.create_object(workspace_id, "a.png", "a.png", "image/png", 10, 16, 9, "5" * 64)
    source = await projects.create_asset(project.id, source_object.id, "source")
    service = ImageEditingService(None, projects, LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    session = await service.create_session(project.id, source.id)
    archived = await service.archive_session(session.id)
    assert archived.status == "archived" and archived.archived_at is not None
    assert await service.list_sessions(project.id) == []
    assert len(await service.list_sessions(project.id, include_archived=True)) == 1
