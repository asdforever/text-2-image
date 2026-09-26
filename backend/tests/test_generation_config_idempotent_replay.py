import asyncio
from copy import deepcopy
from uuid import UUID

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.prompt_repository import MemoryPromptRepository


def test_publish_retry_replays_history_after_bound_prompt_version_is_deleted() -> None:
    async def run() -> None:
        prompts = MemoryPromptRepository()
        template = await prompts.create_template(
            code="replay-prompt",
            name="重放提示词",
            kind="generation",
            kind_name="图片生成",
            execution_target="image",
        )
        version = await prompts.create_version(template, body="历史正文")
        repository = InMemoryGenerationConfigRepository()
        service = GenerationConfigService(
            repository,
            LocalSingleUserIdentityProvider(
                IdentityContext(UUID(int=11), UUID(int=11), "owner")
            ),
            MemoryIdempotencyStore(),
            SystemClock(),
            prompt_repository=prompts,
        )
        initial = await service.get_published()
        draft = deepcopy(initial.content)
        draft["marketBindings"]["taobao"] = {
            "promptTemplateId": str(template.id),
            "promptVersionId": str(version.id),
        }
        await service.replace_draft(draft, initial.version_no)
        first = await service.publish("replay-key")
        await prompts.delete_template(template.id)

        replay = await service.publish("replay-key")

        assert replay.version_no == first.version_no
        assert replay.content["marketBindings"]["taobao"]["versionNo"] == 1
        assert len(await repository.list_versions(UUID(int=11))) == 2

    asyncio.run(run())
