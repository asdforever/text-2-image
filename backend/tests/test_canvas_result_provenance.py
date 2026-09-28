from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone

import pytest

from backend.app.application.canvas_lineage import canvas_generation_steps


@pytest.mark.asyncio
async def test_generation_lineage_exposes_actual_batch_identity_for_result_grouping():
    project_id, workspace_id, batch_id, asset_id = (uuid4() for _ in range(4))
    created = datetime(2026, 9, 24, tzinfo=timezone.utc)
    batch = SimpleNamespace(id=batch_id, project_id=project_id, workspace_id=workspace_id,
                            source_asset_id=uuid4(), kind="hero", status="succeeded",
                            snapshot={}, created_at=created)
    module = SimpleNamespace(id=uuid4(), snapshot={"selection": {"module": {"mode": "hero", "label": "细节图"}}}, final_prompt="", confirmed_task_prompt="")
    asset = SimpleNamespace(id=asset_id, state="available", generation_snapshot_id=uuid4())

    class Batches:
        async def get_slot_execution(self, slot_id):
            assert slot_id == asset.generation_snapshot_id
            return SimpleNamespace(batch=batch, module_task=module)

    steps = await canvas_generation_steps(project_id, workspace_id, [asset], Batches(), [])
    assert steps[0]["batchId"] == str(batch_id)
    assert steps[0]["batchCreatedAt"] == created.isoformat()
    assert steps[0]["outputAssetIds"] == [str(asset_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hero", "suite"])
@pytest.mark.parametrize("effective", [True, False])
async def test_canvas_projects_frozen_design_for_each_task(kind, effective):
    from copy import deepcopy
    project_id, workspace_id = uuid4(), uuid4()
    outline = {"taskId": "task-a", "taskTitle": "场景图", "informationQuestion": "在哪使用", "visualMechanism": "真实场景", "productPresence": "full", "compositionBrief": "桌面与自然光"}
    prompt = {"selection": {"module": {"label": "自由创作"}, "moduleParameters": [{"key": "构图要求", "value": "保留右侧留白"}]}, "constraints": {"market": {"content": "冻结的平台要求"}}}
    if effective:
        prompt["effectiveTaskOutline"] = {**outline, "informationQuestion": "", "productPresence": "none"}
    snapshot = {"taskId": "task-a", "promptSnapshot": prompt} if kind == "suite" else {"taskId": "task-a", **prompt}
    before = deepcopy(snapshot)
    batch = SimpleNamespace(id=uuid4(), project_id=project_id, workspace_id=workspace_id, source_asset_id=uuid4(), kind=kind, status="succeeded", created_at=datetime.now(timezone.utc), snapshot={"selection": {"providerModel": "frozen-model", "moduleParameters": [{"key": "构图要求", "value": "不能覆盖本图构图"}]}, "planningMaster": {"modules": [{**outline, "taskId": "task-other", "taskTitle": "不能串图"}, outline]}})
    module = SimpleNamespace(id=uuid4(), snapshot=snapshot, final_prompt="最终词", confirmed_task_prompt="确认词")
    asset = SimpleNamespace(id=uuid4(), state="available", generation_snapshot_id=uuid4())
    class Batches:
        async def get_slot_execution(self, slot_id):
            return SimpleNamespace(batch=batch, module_task=module)
    step = (await canvas_generation_steps(project_id, workspace_id, [asset], Batches(), []))[0]
    design = step["parameters"]["designBrief"]
    assert design["taskTitle"] == "场景图"
    assert design["informationQuestion"] == ("" if effective else "在哪使用")
    assert design["productPresence"] == ("none" if effective else "full")
    assert design["compositionBrief"] == "桌面与自然光"
    assert design["compositionRequirements"] == ["保留右侧留白"]
    assert step["parameters"]["providerModel"] == "frozen-model"
    assert step["constraints"]["market"]["content"] == "冻结的平台要求"
    assert snapshot == before
