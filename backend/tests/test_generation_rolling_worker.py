import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.application.batch_generation_confirmation_service import BatchGenerationConfirmationService
from backend.app.application.batch_generation_worker import BatchGenerationWorker
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository
from backend.tests.test_batch_generation_compile_service import _fixture, _input
from backend.tests.test_batch_generation_repository import _queued_suite_batch
from backend.tests.test_batch_generation_worker import SuccessEditor, _compiled_prompts


@pytest.mark.asyncio
async def test_worker_refills_free_capacity_before_slowest_image_finishes():
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "rolling")
    await BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider).confirm_batch(
        fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm-rolling"
    )
    release = asyncio.Event()
    third_started = asyncio.Event()

    class Editor(SuccessEditor):
        calls = 0
        active = 0
        peak = 0

        async def edit(self, request):
            self.calls += 1
            index = self.calls
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if index == 1:
                    await release.wait()
                if index == 3:
                    third_started.set()
                return await super().edit(request)
            finally:
                self.active -= 1

    editor = Editor()
    worker = BatchGenerationWorker(
        repository=fixture.repository, project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider),
        image_editor=editor, worker_id="rolling-test", concurrency=2,
    )
    running = asyncio.create_task(worker.run_once(limit=2, refill=True))
    try:
        await asyncio.wait_for(third_started.wait(), 2)
        assert not running.done()
        assert editor.peak == 2
    finally:
        release.set()
        if not running.done():
            await asyncio.wait_for(running, 2)
    assert await running == 3
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail.progress.succeeded == 3


@pytest.mark.asyncio
async def test_active_lease_renewal_protects_long_request_and_rejects_old_owner():
    repo = InMemoryBatchGenerationRepository()
    workspace = uuid4()
    await _queued_suite_batch(repo, workspace, first_count=1, second_count=1)
    now = datetime.now(timezone.utc)
    slot = (await repo.claim_queued_slots("owner", limit=1, lease_duration=timedelta(seconds=10), now=now))[0]
    await repo.mark_dispatching(slot.id, slot.lease_token, now)
    assert not await repo.renew_slot_lease(slot.id, uuid4(), lease_duration=timedelta(seconds=10), now=now)
    assert await repo.renew_slot_lease(slot.id, slot.lease_token, lease_duration=timedelta(seconds=10), now=now + timedelta(seconds=8))
    assert await repo.recover_expired_leases(now + timedelta(seconds=11)) == 0
    assert await repo.recover_expired_leases(now + timedelta(seconds=19)) == 1
    assert not await repo.renew_slot_lease(slot.id, slot.lease_token, lease_duration=timedelta(seconds=10), now=now + timedelta(seconds=20))
    detail = await repo.get_slot_execution(slot.id)
    assert detail.slot.status == "needs_retry"


@pytest.mark.asyncio
async def test_expired_lease_cannot_be_revived_before_recovery():
    repo = InMemoryBatchGenerationRepository()
    await _queued_suite_batch(repo, uuid4(), first_count=1, second_count=1)
    now = datetime.now(timezone.utc)
    slot = (await repo.claim_queued_slots("owner", limit=1, lease_duration=timedelta(seconds=10), now=now))[0]
    assert not await repo.renew_slot_lease(slot.id, slot.lease_token, lease_duration=timedelta(seconds=10), now=now + timedelta(seconds=10))
    assert await repo.recover_expired_leases(now + timedelta(seconds=10)) == 1


async def _queued_worker_fixture():
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "worker-safety")
    await BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider).confirm_batch(
        fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm-safety"
    )
    assets = ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider)
    worker = BatchGenerationWorker(
        repository=fixture.repository, project_repository=fixture.projects,
        project_storage=fixture.storage, project_asset_service=assets,
        image_editor=SuccessEditor(), worker_id="safety-test", concurrency=1,
    )
    return fixture, batch, worker


@pytest.mark.asyncio
async def test_shutdown_finishes_inflight_persistence_without_orphan_assets(monkeypatch):
    fixture, batch, worker = await _queued_worker_fixture()
    persisted = asyncio.Event()
    release = asyncio.Event()
    create = worker.project_asset_service.create_generated_asset

    async def delayed_create(*args, **kwargs):
        asset = await create(*args, **kwargs)
        persisted.set()
        await release.wait()
        return asset

    monkeypatch.setattr(worker.project_asset_service, "create_generated_asset", delayed_create)
    running = asyncio.create_task(worker.run_once(limit=1, refill=True))
    await asyncio.wait_for(persisted.wait(), 2)
    running.cancel()
    await asyncio.sleep(.01)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    generated = [a for a in await worker.project_asset_service.list_assets(fixture.project_id) if a.kind == "generated"]
    assert len(generated) == 1
    assert detail.progress.succeeded == 1
    assert detail.progress.queued == 2
    assert {s.generated_asset_id for s in detail.slots if s.status == "succeeded"} == {generated[0].id}


@pytest.mark.asyncio
async def test_hung_provider_has_wall_clock_deadline_and_does_not_retry():
    fixture, batch, worker = await _queued_worker_fixture()

    class HungEditor(SuccessEditor):
        calls = 0
        async def edit(self, request):
            self.calls += 1
            await asyncio.Event().wait()

    editor = HungEditor()
    worker.image_editor = editor
    worker.provider_timeout_seconds = .02
    assert await asyncio.wait_for(worker.run_once(limit=1, refill=True), 2) == 0
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert editor.calls == 3
    assert detail.progress.needs_retry == 3
    assert {s.error_code for s in detail.slots} == {"PROVIDER_DISPATCH_UNKNOWN"}
    assert await worker.run_once(limit=1, refill=True) == 0
    assert editor.calls == 3
    for slot in detail.slots:
        attempts = await fixture.repository.list_attempts(slot.id, fixture.workspace_id)
        assert attempts[-1].status == "needs_retry"


@pytest.mark.asyncio
async def test_timeout_after_user_cancel_finishes_cancelled_batch():
    fixture, batch, worker = await _queued_worker_fixture()

    class CancelledEditor(SuccessEditor):
        async def edit(self, request):
            await fixture.repository.cancel_batch(batch.id, fixture.workspace_id)
            await asyncio.Event().wait()

    worker.image_editor = CancelledEditor()
    worker.provider_timeout_seconds = .02
    assert await asyncio.wait_for(worker.run_once(limit=1, refill=True), 2) == 0
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail.batch.status == "cancelled"
    assert detail.progress.cancelled == 3


@pytest.mark.asyncio
async def test_live_worker_renews_long_call_while_other_work_keeps_draining(monkeypatch):
    fixture, batch, worker = await _queued_worker_fixture()
    original_renew = fixture.repository.renew_slot_lease
    renewed = asyncio.Event()
    release = asyncio.Event()

    async def renew(*args, **kwargs):
        result = await original_renew(*args, **kwargs)
        if result:
            renewed.set()
        return result

    class WaitingEditor(SuccessEditor):
        async def edit(self, request):
            await release.wait()
            return await super().edit(request)

    monkeypatch.setattr(fixture.repository, "renew_slot_lease", renew)
    worker.image_editor = WaitingEditor()
    worker.lease_seconds = .3
    running = asyncio.create_task(worker.run_once(limit=1, refill=True, poll_interval=.1))
    try:
        await asyncio.wait_for(renewed.wait(), 2)
        detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
        active = next(slot for slot in detail.slots if slot.status == "dispatching")
        assert (active.lease_expires_at - active.dispatched_at).total_seconds() > .35
    finally:
        release.set()
        await asyncio.wait_for(running, 2)
    assert await running == 3


@pytest.mark.asyncio
async def test_refill_recovers_undispatched_lease_without_waiting_for_all_calls(monkeypatch):
    fixture, batch, worker = await _queued_worker_fixture()
    original_read = fixture.repository.get_slot_execution
    failed = False
    third_started = asyncio.Event()
    release = asyncio.Event()

    async def read(slot_id):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("temporary read interruption before dispatch")
        return await original_read(slot_id)

    class WaitingEditor(SuccessEditor):
        calls = 0
        async def edit(self, request):
            self.calls += 1
            if self.calls == 1:
                await release.wait()
            if self.calls == 3:
                third_started.set()
            return await super().edit(request)

    monkeypatch.setattr(fixture.repository, "get_slot_execution", read)
    worker.image_editor = WaitingEditor()
    worker.concurrency = 2
    worker.lease_seconds = .3
    running = asyncio.create_task(worker.run_once(limit=2, refill=True, poll_interval=.1))
    try:
        await asyncio.wait_for(third_started.wait(), 2)
        assert not running.done()
    finally:
        release.set()
        await asyncio.wait_for(running, 2)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail.progress.succeeded == 3
