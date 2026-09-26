"""图片编辑 Postgres 仓储的结构与数据库契约测试。"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.application.image_editing_service import ImageOcrResultRecord
from backend.app.core.config import get_settings
from backend.app.db import create_engine, create_session_factory
from backend.app.image_editing_repository import (
    ImageEditRevisionConflict,
    ImageEditVersionRecord,
    PostgresImageEditingRepository,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend" / "app" / "image_editing_repository.py"

CONTRACT_METHODS = (
    "async def create_session",
    "async def get_session",
    "async def list_sessions",
    "async def save_operation",
    "async def remove_operation",
    "async def get_ocr_result",
    "async def save_ocr_result",
    "async def create_task",
    "async def get_task",
    "async def complete_attempt",
    "async def add_version",
    "async def retry_attempt",
    "async def select_version",
    "async def archive_session",
)


def test_image_editing_repository_exposes_both_implementations() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "class InMemoryImageEditingRepository" in source
    assert "class PostgresImageEditingRepository" in source
    for method in CONTRACT_METHODS:
        # 内存实现与 Postgres 实现各一份，签名必须保持一一对应
        assert source.count(method) >= 2, method
    assert "async with self.sessions() as db, db.begin()" in source
    assert "FOR UPDATE" in source
    assert "to_regclass('project_workbench.image_edit_tasks')" in source
    assert "submit_idempotency_key" in source


def test_main_wires_the_postgres_image_editing_repository() -> None:
    main_source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert "PostgresImageEditingRepository(session_factory)" in main_source
    assert "InMemoryImageEditingRepository()" in main_source


@pytest.mark.asyncio
async def test_postgres_image_editing_repository_persists_the_full_flow() -> None:
    """会话、操作、任务、尝试、版本、OCR 全部落到 image_edit_* 表。

    每个仓储方法使用自己的事务（与生产路径一致），测试数据挂在一个临时项目下，
    结束时删除项目，靠 ON DELETE CASCADE 清干净。
    """
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")

    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    workspace_id = settings.local_workspace_id
    project_id = uuid4()

    try:
        async with sessions() as db, db.begin():
            await db.execute(
                text(
                    "INSERT INTO project_workbench.projects (id, workspace_id, name) "
                    "VALUES (:id, :workspace_id, :name)"
                ),
                {"id": project_id, "workspace_id": workspace_id, "name": "图片编辑仓储契约"},
            )

        repository = PostgresImageEditingRepository(sessions)

        session = await repository.create_session(
            workspace_id, project_id, uuid4(), {"assetId": "source-1"}
        )
        assert (session.revision, session.status) == (1, "draft")

        first = await repository.save_operation(
            session.id,
            workspace_id,
            {"operationId": "op-1", "type": "erase", "ordinal": 1},
            expected_revision=1,
        )
        assert first.revision == 2
        assert [item["operationId"] for item in first.operations_snapshot] == ["op-1"]

        with pytest.raises(ImageEditRevisionConflict):
            await repository.save_operation(
                session.id,
                workspace_id,
                {"operationId": "op-2", "type": "expand", "ordinal": 2},
                expected_revision=1,
            )

        second = await repository.save_operation(
            session.id,
            workspace_id,
            {"operationId": "op-2", "type": "expand", "ordinal": 2},
            expected_revision=2,
        )
        assert second.revision == 3, "冲突不能污染后续修订"
        assert [item["operationId"] for item in second.operations_snapshot] == ["op-1", "op-2"]

        removed = await repository.remove_operation(
            session.id, workspace_id, "op-1", expected_revision=3
        )
        assert [item["operationId"] for item in removed.operations_snapshot] == ["op-2"]

        async with sessions() as db:
            mirrored = await db.scalar(
                text(
                    "SELECT count(*) FROM project_workbench.image_edit_operations "
                    "WHERE session_id=:id"
                ),
                {"id": session.id},
            )
        assert mirrored == 1, "草稿操作必须镜像到规范化的 image_edit_operations 表"

        task = await repository.create_task(
            removed,
            {"summary": "白底图"},
            {"outputKind": "white_background"},
            "submit-key-1",
        )
        replay = await repository.create_task(
            removed,
            {"summary": "白底图"},
            {"outputKind": "white_background"},
            "submit-key-1",
        )
        assert replay.id == task.id, "相同幂等键必须复用同一个任务"
        assert len(task.attempts) == 1
        assert (await repository.get_session(session.id, workspace_id)).status == "submitted"

        await repository.complete_attempt(
            task.id, task.attempts[0].id, success=False, error="provider failed"
        )
        failed = await repository.get_task(task.id, workspace_id)
        assert failed.status == "failed"
        assert failed.attempts[0].error_message == "provider failed"

        retried = await repository.retry_attempt(failed.attempts[0].id, workspace_id)
        assert retried is not None
        assert [item.attempt_number for item in retried.attempts] == [1, 2]
        assert retried.status == "queued"

        await repository.complete_attempt(task.id, retried.attempts[1].id, success=True)
        assert (await repository.get_task(task.id, workspace_id)).status == "succeeded"

        version = ImageEditVersionRecord(
            id=uuid4(),
            task_id=task.id,
            attempt_id=retried.attempts[1].id,
            version_number=1,
            object_key="image-edit/demo/1.png",
            preview_url="https://example.test/1.png",
            source_snapshot={"assetId": "source-1"},
            prompt_snapshot={"summary": "白底图"},
            config_snapshot={"outputKind": "white_background"},
        )
        await repository.add_version(task.id, version)
        assert version.is_current is True

        loaded = await repository.get_task(task.id, workspace_id)
        assert loaded.current_version_id == version.id
        assert len(loaded.versions) == 1
        assert loaded.versions[0].is_current is True

        selected = await repository.select_version(task.id, version.id, workspace_id, "final")
        assert selected.is_final is True
        assert (await repository.get_task(task.id, workspace_id)).final_version_id == version.id

        ocr = ImageOcrResultRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            session_id=session.id,
            source_version_id=session.source_version_id,
            request_fingerprint="f" * 64,
            text="识别到的文字",
            regions=[{"x": 1, "y": 2}],
            provider_snapshot={"provider": "contract"},
        )
        await repository.save_ocr_result(ocr)
        cached = await repository.get_ocr_result(
            session.id, session.source_version_id, "f" * 64
        )
        assert cached is not None
        assert cached.text == "识别到的文字"
        assert cached.regions == [{"x": 1, "y": 2}]

        assert await repository.get_task(task.id, uuid4()) is None
        assert await repository.get_session(session.id, uuid4()) is None

        archived = await repository.archive_session(session.id, workspace_id)
        assert archived.status == "archived"
        assert await repository.list_sessions(project_id, workspace_id) == []
        assert (
            len(await repository.list_sessions(project_id, workspace_id, include_archived=True))
            == 1
        )
    finally:
        async with sessions() as db, db.begin():
            await db.execute(
                text("DELETE FROM project_workbench.projects WHERE id=:id"),
                {"id": project_id},
            )
        await engine.dispose()
