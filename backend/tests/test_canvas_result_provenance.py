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
