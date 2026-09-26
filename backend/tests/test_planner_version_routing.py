from uuid import uuid4

import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.hero_generation_repository import HeroGenerationTaskRecord
from backend.app.batch_generation_repository import GenerationBatchRecord
from backend.app.suite_planning_repository import SuitePlanRecord, SuitePlanDetail
from backend.app.routes.hero_generations import _task_view
from backend.app.routes.batch_generations import _batch_view
from backend.app.routes.suite_plans import _plan_view


@pytest.mark.parametrize("version", [None, "v2"])
def test_api_projects_frozen_planner_version_for_confirmation_ui(version):
    workspace, project, source = uuid4(), uuid4(), uuid4()
    snapshot = {"plannerVersion": version} if version else {}
    hero = HeroGenerationTaskRecord(
        id=uuid4(), workspace_id=workspace, project_id=project, source_asset_id=source,
        status="awaiting_confirmation", compile_idempotency_key="hero",
        compile_fingerprint="hero-fingerprint", snapshot=snapshot,
    )
    batch = GenerationBatchRecord(
        id=uuid4(), workspace_id=workspace, project_id=project, source_asset_id=source,
        status="awaiting_confirmation", compile_idempotency_key="batch",
        compile_fingerprint="batch-fingerprint", snapshot=snapshot,
    )
    plan = SuitePlanRecord(
        id=uuid4(), workspace_id=workspace, project_id=project,
        status="awaiting_confirmation", revision=1, requested_module_count=1,
        compile_idempotency_key="suite", compile_fingerprint="suite-fingerprint",
        snapshot=snapshot,
    )
    views = [_task_view(hero, project), _batch_view(batch), _plan_view(SuitePlanDetail(plan, []))]
    for view in views:
        assert view["plannerVersion"] == "v2"


def test_new_app_uses_v2_even_if_obsolete_rollback_variable_is_set(monkeypatch):
    monkeypatch.setenv("MODULE_PLANNER_VERSION", "v1")
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None))
    for name in ("hero_generation_service", "batch_generation_service", "suite_planning_service"):
        assert not hasattr(getattr(app.state, name), "planner_version")
