import asyncio
from copy import deepcopy
from uuid import UUID

import pytest

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.prompt_repository import MemoryPromptRepository


def _service(prompt_repository) -> GenerationConfigService:
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=11), UUID(int=11), "owner")
    )
    return GenerationConfigService(
        InMemoryGenerationConfigRepository(),
        identity,
        MemoryIdempotencyStore(),
        SystemClock(),
        prompt_repository=prompt_repository,
    )


async def _prompt(repository: MemoryPromptRepository, code: str):
    template = await repository.create_template(
        code=code,
        name=f"{code} 提示词",
        kind="generation",
        kind_name="图片生成",
        execution_target="image",
    )
    version = await repository.create_version(template, body=f"{code} body")
    return template, version


def test_publish_resolves_all_binding_slots_to_specific_prompt_version_metadata() -> None:
    async def run() -> None:
        prompts = MemoryPromptRepository()
        template, version = await _prompt(prompts, "catalog")
        service = _service(prompts)
        current = await service.get_published()
        draft = deepcopy(current.content)
        slots = [
            ("marketBindings", "taobao", "market"),
            ("heroBindings", "hero-kv", "hero-module"),
            ("suiteBindings", "suite-hero", "suite-module"),
        ]
        for field, target_id, _slot in slots:
            draft[field][target_id] = {
                "promptTemplateId": str(template.id),
                "promptVersionId": str(version.id),
            }
        draft["modelBindings"]["gpt-image-2-5"] = {"promptTemplateId":"obsolete", "promptVersionId":"obsolete"}
        await service.replace_draft(draft, current.version_no)

        published = await service.publish()
        assert published.content["modelBindings"]["gpt-image-2-5"] is None

        for field, target_id, slot in slots:
            binding = published.content[field][target_id]
            assert binding == {
                "promptTemplateId": str(template.id),
                "promptVersionId": str(version.id),
                "templateName": "catalog 提示词",
                "versionNo": 1,
                "contentSha256": version.content_sha256,
                "slot": slot,
                "targetId": target_id,
            }

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing", "ownership"])
def test_publish_rejects_missing_or_wrongly_owned_prompt_version(failure: str) -> None:
    async def run() -> None:
        prompts = MemoryPromptRepository()
        template, version = await _prompt(prompts, "first")
        other_template, _other_version = await _prompt(prompts, "other")
        service = _service(prompts)
        current = await service.get_published()
        draft = deepcopy(current.content)
        draft["marketBindings"]["taobao"] = {
            "promptTemplateId": str(other_template.id if failure == "ownership" else template.id),
            "promptVersionId": str(version.id if failure == "ownership" else UUID(int=999)),
        }
        await service.replace_draft(draft, current.version_no)

        with pytest.raises(AppError) as caught:
            await service.publish()

        assert caught.value.code == (
            "GENERATION_CONFIG_PROMPT_OWNERSHIP"
            if failure == "ownership"
            else "GENERATION_CONFIG_PROMPT_VERSION_NOT_FOUND"
        )
        assert (await service.get_published()).version_no == 1

    asyncio.run(run())
