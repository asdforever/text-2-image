import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.app.hero_generation_repository import PostgresHeroGenerationRepository
from backend.app.batch_generation_repository import PostgresBatchGenerationRepository
from backend.app.suite_planning_repository import PostgresSuitePlanningRepository
from backend.app.core.errors import AppError


class RecordingSession:
    def __init__(self, scalar):
        self.calls = []
        self.scalar = scalar

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def begin(self):
        return self

    async def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters))
        return SimpleNamespace(scalar_one_or_none=lambda: self.scalar)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hero", "batch", "suite"])
async def test_postgres_snapshot_save_serializes_parent_and_every_module(kind):
    task_id, workspace_id = uuid4(), uuid4()
    session = RecordingSession(task_id)
    snapshots = {
        "stylePlanning": {"inputStyle": {"promptVersionId": str(uuid4())}, "stylePrompt": "暖灰背景"},
        "constraints": {"style": {"source": "style_planner_result", "content": "暖灰背景"}},
    }
    children = [SimpleNamespace(id=uuid4(), module_key=key) for key in ("one", "two")]
    child_snapshots = {child.module_key: {**snapshots, "module": child.module_key} for child in children}
    if kind == "hero":
        repository = PostgresHeroGenerationRepository(lambda: session)
        await repository.save_planning_snapshot(task_id, workspace_id, snapshots)
    elif kind == "batch":
        repository = PostgresBatchGenerationRepository(lambda: session)
        repository._locked_batch = AsyncMock(return_value=SimpleNamespace(status="compiling_prompt"))
        repository._tasks = AsyncMock(return_value=children)
        await repository.save_planning_snapshot(task_id, workspace_id, snapshots, child_snapshots)
        repository._locked_batch.assert_awaited_once_with(session, task_id, workspace_id)
    else:
        repository = PostgresSuitePlanningRepository(lambda: session)
        repository._locked_plan = AsyncMock(return_value=SimpleNamespace(status="compiling"))
        repository._modules = AsyncMock(return_value=children)
        await repository.save_planning_snapshot(task_id, workspace_id, snapshots, child_snapshots)
        repository._locked_plan.assert_awaited_once_with(session, task_id, workspace_id)
    assert len(session.calls) == (1 if kind == "hero" else 3)
    assert json.loads(session.calls[0][1]["snapshot"]) == snapshots
    for child, (_, parameters) in zip(children, session.calls[1:]):
        assert parameters["id"] == child.id
        assert json.loads(parameters["snapshot"]) == child_snapshots[child.module_key]


@pytest.mark.asyncio
async def test_postgres_hero_snapshot_save_rejects_missing_or_noncompiling_task():
    session = RecordingSession(None)
    repository = PostgresHeroGenerationRepository(lambda: session)
    with pytest.raises(AppError) as exc:
        await repository.save_planning_snapshot(uuid4(), uuid4(), {})
    assert exc.value.code == "HERO_GENERATION_INVALID_STATE"
