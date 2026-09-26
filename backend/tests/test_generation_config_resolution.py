import asyncio
from copy import deepcopy
from uuid import UUID

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository


def _service(repository) -> GenerationConfigService:
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=11), UUID(int=11), "owner")
    )
    return GenerationConfigService(
        repository, identity, MemoryIdempotencyStore(), SystemClock()
    )


def test_resolved_configuration_reads_only_current_published_version() -> None:
    async def run() -> None:
        service = _service(InMemoryGenerationConfigRepository())
        published = await service.get_published()
        draft = deepcopy(published.content)
        draft["markets"][0]["label"] = "只在草稿中"
        await service.replace_draft(draft, published.version_no)

        resolved = await service.resolve_published()

        assert resolved["configVersion"] == 1
        assert resolved["contentSha256"] == published.content_sha256
        assert resolved["config"]["markets"][0]["label"] == "淘宝"
        assert resolved["promptBindings"] == []

    asyncio.run(run())


def test_historical_configuration_survives_removal_from_newer_version() -> None:
    async def run() -> None:
        repository = InMemoryGenerationConfigRepository()
        service = _service(repository)
        first = await service.get_published()
        draft = deepcopy(first.content)
        draft["markets"] = [item for item in draft["markets"] if item["id"] != "taobao"]
        draft["marketBindings"].pop("taobao")
        await service.replace_draft(draft, first.version_no)
        second = await service.publish()

        historical = await service.get_version(first.version_no)
        resolved = await service.resolve_published()

        assert historical is not None
        assert any(item["id"] == "taobao" for item in historical.content["markets"])
        assert all(item["id"] != "taobao" for item in second.content["markets"])
        assert all(item["id"] != "taobao" for item in resolved["config"]["markets"])

    asyncio.run(run())
