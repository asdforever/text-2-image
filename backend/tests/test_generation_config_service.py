import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import request_fingerprint
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_catalog import normalize_generation_config
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc)


def _service(repository, workspace: int, store=None) -> GenerationConfigService:
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=workspace), UUID(int=workspace), "owner")
    )
    return GenerationConfigService(
        repository,
        identity,
        store or MemoryIdempotencyStore(),
        _FixedClock(),
    )


def test_generation_config_service_initializes_each_workspace_with_version_one() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        first = await _service(repository, 11).get_published()
        second = await _service(repository, 22).get_published()

        assert first.version_no == second.version_no == 1
        assert first.workspace_id != second.workspace_id
        assert first.content["version"] == 1
        assert first.content["markets"][0]["id"] == "taobao"

    asyncio.run(run())


def test_concurrent_initialization_creates_one_version_one_and_one_draft() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        service = _service(repository, 11)

        published, draft = await asyncio.gather(
            service.get_published(), service.get_draft()
        )

        assert published.version_no == 1
        assert draft.base_version_no == 1
        versions = await repository.list_versions(UUID(int=11))
        assert [item.version_no for item in versions] == [1]
        assert versions[0].content["version"] == 1

    asyncio.run(run())


def test_saved_draft_does_not_change_published_config_and_discard_restores_it() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        service = _service(repository, 11)
        published = await service.get_published()
        draft_content = deepcopy(published.content)
        draft_content["markets"][0]["label"] = "淘宝新名称"

        saved = await service.replace_draft(draft_content, published.version_no, "save-one")

        assert saved.content["markets"][0]["label"] == "淘宝新名称"
        assert (await service.get_published()).content["markets"][0]["label"] == "淘宝"
        restored = await service.discard_draft("discard-one")
        assert restored.base_version_no == published.version_no
        assert restored.content == published.content

    asyncio.run(run())


def test_publish_creates_one_incremented_version_and_replays_idempotently() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        store = MemoryIdempotencyStore()
        service = _service(repository, 11, store)
        initial = await service.get_published()
        draft = deepcopy(initial.content)
        draft["models"][0]["label"] = "新版模型名称"
        await service.replace_draft(draft, initial.version_no, "save-two")

        first = await service.publish("publish-one")
        replay = await service.publish("publish-one")

        assert first.version_no == replay.version_no == 2
        assert first.content["version"] == 2
        assert first.content["savedAt"] == "2026-09-14T08:30:00Z"
        assert len(await repository.list_versions(UUID(int=11))) == 2
        assert (await service.get_draft()).base_version_no == 2

    asyncio.run(run())


def test_concurrent_publish_of_the_same_draft_creates_one_new_version() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        service = _service(repository, 11)
        initial = await service.get_published()
        draft = deepcopy(initial.content)
        draft["models"][0]["label"] = "并发发布模型"
        await service.replace_draft(draft, initial.version_no)

        first, second = await asyncio.gather(
            service.publish("publish-a"), service.publish("publish-b")
        )

        assert {first.version_no, second.version_no} == {2}
        versions = await repository.list_versions(UUID(int=11))
        assert [item.version_no for item in versions] == [1, 2]
        assert versions[-1].content["version"] == 2

    asyncio.run(run())


def test_replace_draft_replay_survives_a_later_publish() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        store = MemoryIdempotencyStore()
        service = _service(repository, 11, store)
        initial = await service.get_published()
        draft = deepcopy(initial.content)
        draft["models"][0]["label"] = "可重放草稿"

        saved = await service.replace_draft(draft, initial.version_no, "draft-replay")
        await service.publish("publish-after-save")
        replay = await service.replace_draft(draft, initial.version_no, "draft-replay")

        assert replay.content == saved.content
        assert replay.base_version_no == saved.base_version_no == 1

    asyncio.run(run())


def test_publish_recovers_an_interrupted_idempotent_request_from_its_version() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        store = MemoryIdempotencyStore()
        service = _service(repository, 11, store)
        initial = await service.get_published()
        draft = deepcopy(initial.content)
        draft["models"][0]["label"] = "中断恢复模型"
        await service.replace_draft(draft, initial.version_no)
        normalized = normalize_generation_config(draft)
        key = "interrupted-publish"
        scope = f"{UUID(int=11)}:POST:/api/generation-config/publish"
        await store.claim(
            scope,
            key,
            request_fingerprint({"content": service._request_content(normalized)}),
        )
        published_without_record = await service.publish()

        recovered = await service.publish(key)

        assert recovered.version_no == published_without_record.version_no == 2
        assert len(await repository.list_versions(UUID(int=11))) == 2

    asyncio.run(run())


def test_publish_rejects_stale_draft_without_changing_current_version() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        service = _service(repository, 11)
        initial = await service.get_published()
        await service.replace_draft(initial.content, initial.version_no, "save-three")
        external = deepcopy(initial.content)
        external["version"] = 2
        external["models"][0]["label"] = "外部发布模型"
        await repository.publish(UUID(int=11), external)

        with pytest.raises(AppError) as caught:
            await service.publish("publish-stale")

        assert caught.value.code == "GENERATION_CONFIG_DRAFT_CONFLICT"
        assert (await service.get_published()).version_no == 2

    asyncio.run(run())
