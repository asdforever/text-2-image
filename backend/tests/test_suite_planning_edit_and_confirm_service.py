from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from backend.app.application.suite_planning_confirmation_service import (
    SuitePlanningConfirmationService,
)
from backend.app.application.suite_planning_service import (
    SuitePlanModuleUpdateInput,
    SuitePlanningService,
)
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository
from backend.app.core.errors import AppError
from backend.app.suite_planning_repository import (
    InMemorySuitePlanningRepository,
    SuitePlanModuleCompilation,
    SuitePlanModuleInput,
)


class Identity:
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id

    def get_context(self):
        return type("Context", (), {"workspace_id": self.workspace_id})()


def _module(key: str, position: int, count: int = 1) -> SuitePlanModuleInput:
    return SuitePlanModuleInput(key, position, count, key, prompt_snapshot={"constraints": {}})


@pytest.mark.asyncio
async def test_application_rejects_direct_prompt_edits() -> None:
    workspace_id, project_id = uuid4(), uuid4()
    plans = InMemorySuitePlanningRepository()
    plan, _ = await plans.create_compiling(
        workspace_id, project_id, "compile", "a" * 64, {}, [_module("hero", 1)],
    )
    service = SuitePlanningService.__new__(SuitePlanningService)
    service.plan_repository = plans
    service.identity_provider = Identity(workspace_id)
    with pytest.raises(AppError) as error:
        await service.update_module(
            project_id, plan.id,
            SuitePlanModuleUpdateInput(module_id=uuid4(), expected_plan_revision=1, expected_module_revision=1,
                                       current_task_prompt="override"),
        )
    assert error.value.code == "V2_PROMPT_READ_ONLY"


@dataclass
class _ConfirmationFixture:
    workspace_id: UUID
    project_id: UUID
    plan_id: UUID
    plans: InMemorySuitePlanningRepository
    batches: InMemoryBatchGenerationRepository
    service: SuitePlanningConfirmationService


async def _confirmation_fixture() -> _ConfirmationFixture:
    workspace_id, project_id = uuid4(), uuid4()
    plans = InMemorySuitePlanningRepository()
    plan, _ = await plans.create_compiling(
        workspace_id, project_id, "compile", "b" * 64,
        {
            "sourceAssets": [{"assetId": str(uuid4()), "sha256": "c" * 64}],
            "selection": {"resolution": "标准 1K"},
            "constraints": {
                "authenticity": {"content": "真实性约束", "source": "server_policy", "contentSha256": "1" * 64},
                "market": {"content": "平台约束", "source": "market_guidance", "contentSha256": "2" * 64},
                "style": {"content": "风格约束", "source": "style_description", "contentSha256": "3" * 64},
            },
        },
        [_module("hero", 1, 2), _module("scene", 2, 3)],
    )
    await plans.mark_awaiting_confirmation(
        plan.id, workspace_id,
        {
            "hero": SuitePlanModuleCompilation("首屏", "产品居中", "hero prompt", {"visibleFacts": ["黑色"]}),
            "scene": SuitePlanModuleCompilation("场景", "书房", "scene prompt", {"unconfirmedItems": ["材质"]}),
        },
    )
    batches = InMemoryBatchGenerationRepository()
    identity = Identity(workspace_id)
    service = SuitePlanningConfirmationService(
        plan_repository=plans,
        batch_repository=batches,
        identity_provider=identity,
    )
    return _ConfirmationFixture(workspace_id, project_id, plan.id, plans, batches, service)


@pytest.mark.asyncio
async def test_confirmation_rejects_stale_revision_without_creating_batch() -> None:
    fixture = await _confirmation_fixture()
    detail = await fixture.plans.get_plan_detail(fixture.plan_id, fixture.workspace_id, fixture.project_id)
    assert detail is not None
    with pytest.raises(AppError) as conflict:
        await fixture.service.confirm_plan(
            fixture.project_id,
            fixture.plan_id,
            expected_plan_revision=detail.plan.revision - 1,
            module_task_prompts={"hero": "确认首屏", "scene": "确认场景"},
            idempotency_key="confirm-stale",
        )
    assert conflict.value.code == "SUITE_PLAN_REVISION_CONFLICT"
    assert fixture.batches._batches == {}
