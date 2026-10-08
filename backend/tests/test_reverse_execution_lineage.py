from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone

from app.application import canvas_lineage


def test_reverse_lineage_uses_batch_snapshots_and_keeps_retry_outputs():
    source, first, retry, other = [uuid4() for _ in range(4)]
    assets = [SimpleNamespace(id=i, state="available", source_kind="reverse_execution", source_snapshot={}) for i in (source, first, retry, other)]
    batch = SimpleNamespace(id=uuid4(), plan_id=uuid4(), batch_no=2,
        created_at=datetime.now(timezone.utc), document={"planName": "电竞场景", "sourceAssetId": str(source),
            "status": "completed", "versionId": str(uuid4()), "outputSettings": {"resolution": "2K"},
            "tasks": [{"id": "task", "ordinal": 1, "title": "电竞桌面", "promptDraft": "冻结提示词",
                "attempts": [{"id": "a1", "status": "succeeded", "generatedAssetId": str(first)},
                    {"id": "a2", "status": "succeeded", "generatedAssetId": str(retry)}]}]})
    steps = canvas_lineage.reverse_execution_steps([batch], assets)
    assert len(steps) == 1
    step = steps[0]
    assert step["batchId"] == str(batch.id)
    assert step["sourceAssetIds"] == [str(source)]
    assert step["outputAssetIds"] == [str(first), str(retry)]
    assert str(other) not in step["outputAssetIds"]
    assert step["finalPrompt"] == "冻结提示词"
    assert step["reversePlanName"] == "电竞场景"
