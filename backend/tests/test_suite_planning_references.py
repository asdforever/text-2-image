from uuid import uuid4

import pytest

from backend.app.application.suite_planning_ports import (
    EmptyPlanningReferenceResolver,
    InMemoryPlanningReferenceResolver,
    PlanningReferenceRequest,
    PlanningReferenceSnapshot,
)
from backend.app.core.errors import AppError


@pytest.mark.asyncio
async def test_empty_reference_resolver_accepts_no_selection_but_never_ignores_ids() -> None:
    resolver = EmptyPlanningReferenceResolver()
    workspace_id = uuid4()

    assert await resolver.resolve(workspace_id, []) == []
    with pytest.raises(AppError) as unavailable:
        await resolver.resolve(
            workspace_id, [PlanningReferenceRequest("knowledge-1", "v1")]
        )
    assert unavailable.value.code == "PLANNING_REFERENCE_PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_memory_reference_resolver_freezes_exact_active_workspace_version() -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    resolver = InMemoryPlanningReferenceResolver(
        [
            PlanningReferenceSnapshot(
                reference_id="knowledge-1",
                version="v2",
                workspace_id=workspace_id,
                title="产品规格资料",
                source="product-library",
                content_sha256="a" * 64,
                field_values={"材质": "铝合金"},
                active=True,
            )
        ]
    )

    snapshots = await resolver.resolve(
        workspace_id, [PlanningReferenceRequest("knowledge-1", "v2")]
    )
    snapshots[0].field_values["材质"] = "被调用方修改"
    restored = await resolver.resolve(
        workspace_id, [PlanningReferenceRequest("knowledge-1", "v2")]
    )

    assert restored[0].field_values == {"材质": "铝合金"}
    with pytest.raises(AppError) as cross_workspace:
        await resolver.resolve(
            other_workspace_id, [PlanningReferenceRequest("knowledge-1", "v2")]
        )
    assert cross_workspace.value.code == "PLANNING_REFERENCE_NOT_FOUND"
    with pytest.raises(AppError) as wrong_version:
        await resolver.resolve(
            workspace_id, [PlanningReferenceRequest("knowledge-1", "v1")]
        )
    assert wrong_version.value.code == "PLANNING_REFERENCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_memory_reference_resolver_rejects_archived_version() -> None:
    workspace_id = uuid4()
    resolver = InMemoryPlanningReferenceResolver(
        [
            PlanningReferenceSnapshot(
                reference_id="archived",
                version="v1",
                workspace_id=workspace_id,
                title="旧资料",
                source="manual",
                content_sha256="b" * 64,
                field_values={},
                active=False,
            )
        ]
    )

    with pytest.raises(AppError) as archived:
        await resolver.resolve(
            workspace_id, [PlanningReferenceRequest("archived", "v1")]
        )
    assert archived.value.code == "PLANNING_REFERENCE_INACTIVE"
