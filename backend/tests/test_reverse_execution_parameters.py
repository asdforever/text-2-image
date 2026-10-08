import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.reverse_execution_parameters import ReverseExecutionParameterPlanner
from app.application.reverse_execution_service import ReverseExecutionService
from app.core.errors import AppError
from app.reverse_execution_repository import InMemoryReverseExecutionRepository
from test_reverse_execution_service import FakeIdentity, FakeProjectRepository, FakeReverseService


class FakePlanner:
    def __init__(self, invalid=False):
        self.invalid = invalid
        self.requests = []

    async def plan_modules(self, request):
        self.requests.append(request)
        tasks = json.loads(request.user_prompt)["tasks"]
        result = {"summary": "按首图和尺寸图分配", "tasks": [
            {"taskId": tasks[1]["id"], "moduleParameters": [{"key": "尺寸", "value": "100×60mm"}]},
            {"taskId": tasks[0]["id"], "moduleParameters": [{"key": "卖点", "value": "静音按键"}]},
        ]}
        if self.invalid:
            result["tasks"][1]["taskId"] = tasks[1]["id"]
        return result


class FakeAssets:
    async def get_asset_details(self, project_id, asset_id):
        return SimpleNamespace(id=asset_id), SimpleNamespace(media_type="image/png")

    async def get_preview(self, project_id, asset_id):
        return SimpleNamespace(data=b"current-product")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_auto_fill_assigns_by_task_identity_and_preserves_structure(invalid):
    planner = FakePlanner(invalid)
    parameter_planner = ReverseExecutionParameterPlanner(planner=planner, project_asset_service=FakeAssets())
    repository = InMemoryReverseExecutionRepository()
    service = ReverseExecutionService(repository, FakeIdentity(uuid4()), FakeProjectRepository(), FakeReverseService(), parameter_planner=parameter_planner)
    project_id, source_id = uuid4(), uuid4()
    created = await service.generate(project_id, uuid4(), source_asset_id=source_id, product_facts={"商品名称": "鼠标"})
    document = deepcopy(created.document)
    document["parameterBrief"] = "静音按键，尺寸100×60mm"
    saved = await service.save(project_id, created.revision, document)
    if invalid:
        with pytest.raises(AppError) as error:
            await service.assign_parameters(project_id, saved.revision)
        assert error.value.code == "REVERSE_PARAMETERS_INVALID_RESPONSE"
        assert (await service.get(project_id)).document == saved.document
        return
    assigned = await service.assign_parameters(project_id, saved.revision)
    assert [task["referenceImageId"] for task in assigned.document["tasks"]] == ["ref-1", "ref-2"]
    assert [task["structure"] for task in assigned.document["tasks"]] == [task["structure"] for task in saved.document["tasks"]]
    assert assigned.document["tasks"][0]["moduleParameters"] == [{"key": "卖点", "value": "静音按键"}]
    assert assigned.document["tasks"][1]["moduleParameters"] == [{"key": "尺寸", "value": "100×60mm"}]
    assert planner.requests[0].image_inputs == [b"current-product"]
    assert "静音按键，尺寸100×60mm" in planner.requests[0].user_prompt
    compiled = await service.compile(project_id, assigned.revision)
    assert "静音按键" in compiled.document["tasks"][0]["promptDraft"]
    assert "100×60mm" not in compiled.document["tasks"][0]["promptDraft"]
    assert "100×60mm" in compiled.document["tasks"][1]["promptDraft"]
    assert "静音按键" not in compiled.document["tasks"][1]["promptDraft"]


@pytest.mark.asyncio
async def test_preview_assignment_failure_keeps_inputs_and_revision_unchanged():
    repository = InMemoryReverseExecutionRepository()
    service = ReverseExecutionService(repository, FakeIdentity(uuid4()), FakeProjectRepository(), FakeReverseService(),
        parameter_planner=ReverseExecutionParameterPlanner(planner=FakePlanner(invalid=True), project_asset_service=FakeAssets()))
    project_id = uuid4()
    created = await service.generate(project_id, uuid4(), source_asset_id=uuid4(), parameter_brief="静音按键")
    with pytest.raises(AppError) as error:
        await service.compile(project_id, created.revision, {"商品名称": "新商品"}, plan_id=created.id)
    assert error.value.code == "REVERSE_PARAMETERS_INVALID_RESPONSE"
    after = await service.get(project_id, created.id)
    assert after.revision == created.revision
    assert after.document == created.document
