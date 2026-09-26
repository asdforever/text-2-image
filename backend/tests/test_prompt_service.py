from pathlib import Path

import pytest

from backend.app.prompt_service import DuplicatePromptVersion, PromptService
from backend.app.prompt_repository import MemoryPromptRepository, PromptRepositoryError


def service(tmp_path: Path) -> PromptService:
    return PromptService(MemoryPromptRepository())


class AtomicCreateFailureRepository(MemoryPromptRepository):
    async def create_template_with_version(self, **_payload):
        raise PromptRepositoryError("PROMPT_CREATE_FAILED")


def test_failed_initial_create_does_not_leave_orphan_template(tmp_path: Path) -> None:
    async def run() -> None:
        repository = AtomicCreateFailureRepository()
        svc = PromptService(repository)
        with pytest.raises(PromptRepositoryError, match="PROMPT_CREATE_FAILED"):
            await svc.create_template({"code": "broken", "name": "Broken", "kind": "planner", "stage": "plan", "execution_target": "llm", "body": "hello"})
        assert repository.templates == {}
        assert repository.versions == {}

    import asyncio
    asyncio.run(run())


def test_new_template_creates_v1_and_default(tmp_path: Path) -> None:
    async def run() -> None:
        result = await service(tmp_path).create_template({"code": "demo.prompt", "name": "Demo", "kind": "planner", "stage": "plan", "execution_target": "llm", "body": "hello"})
        assert result.version.version_no == 1
        assert result.template.default_version_id == result.version.id
        assert result.version.file_sync_status == "synced"

    import asyncio
    asyncio.run(run())


def test_save_from_history_creates_next_version_and_resolves_old(tmp_path: Path) -> None:
    async def run() -> None:
        svc = service(tmp_path)
        first = await svc.create_template({"code": "demo.prompt", "name": "Demo", "kind": "planner", "stage": "plan", "execution_target": "llm", "body": "v1"})
        second = await svc.create_version(first.template.id, first.version.id, {"body": "v2", "change_note": "revise"})
        third = await svc.create_version(first.template.id, first.version.id, {"body": "v3"})
        assert [item.version_no for item in await svc.list_versions(first.template.id)] == [1, 2, 3]
        assert third.version.version_no == 3
        assert (await svc.resolve_version(first.template.id)).id == third.version.id
        assert (await svc.resolve_version(first.template.id, second.version.id)).body == "v2"

    import asyncio
    asyncio.run(run())


def test_identical_content_does_not_create_version(tmp_path: Path) -> None:
    async def run() -> None:
        svc = service(tmp_path)
        first = await svc.create_template({"code": "demo.prompt", "name": "Demo", "kind": "planner", "stage": "plan", "execution_target": "llm", "body": "same"})
        with pytest.raises(DuplicatePromptVersion):
            await svc.create_version(first.template.id, first.version.id, {"body": "same"})

    import asyncio
    asyncio.run(run())
