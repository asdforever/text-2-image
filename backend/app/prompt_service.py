from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from .prompt_repository import PromptRepositoryError, PromptTemplateRecord, PromptVersionRecord, prompt_hash


class DuplicatePromptVersion(ValueError):
    pass


@dataclass(frozen=True)
class PromptSaveResult:
    template: PromptTemplateRecord
    version: PromptVersionRecord


class PromptService:
    def __init__(self, repository) -> None:
        self.repository = repository

    async def create_template(self, payload: dict, *, idempotency_key: str | None = None) -> PromptSaveResult:
        atomic_create = getattr(self.repository, "create_template_with_version", None)
        if atomic_create is not None:
            template, version = await atomic_create(
                code=payload["code"], name=payload["name"], kind=payload["kind"],
                kind_name=payload.get("kind_name") or payload.get("stage") or payload["kind"], execution_target=payload["execution_target"],
                body=payload["body"], user_prompt_template=payload.get("user_prompt_template", ""),
                input_schema=payload.get("input_schema"), output_schema=payload.get("output_schema"),
                applicability=payload.get("applicability"), generation_params=payload.get("generation_params"),
                source=payload.get("source", "marketplace"),
                change_note=payload.get("change_note"), idempotency_key=idempotency_key,
                category_id=payload.get("category_id"),
                stage=payload.get("stage", "plan"),
            )
        else:
            template = await self.repository.create_template(code=payload["code"], name=payload["name"], kind=payload["kind"], kind_name=payload.get("kind_name") or payload.get("stage") or payload["kind"], execution_target=payload["execution_target"], category_id=payload.get("category_id"), stage=payload.get("stage", "plan"))
            try:
                version = await self.repository.create_version(template, body=payload["body"], user_prompt_template=payload.get("user_prompt_template", ""), input_schema=payload.get("input_schema"), output_schema=payload.get("output_schema"), applicability=payload.get("applicability"), generation_params=payload.get("generation_params"), source=payload.get("source", "marketplace"), change_note=payload.get("change_note"))
            except Exception:
                if hasattr(self.repository, "templates"):
                    self.repository.templates.pop(template.id, None)
                raise
        return PromptSaveResult(template, version)

    async def create_version(self, template_id: UUID, base_version_id: UUID, payload: dict, *, idempotency_key: str | None = None) -> PromptSaveResult:
        template = await self.repository.get_template(template_id)
        if not template:
            raise PromptRepositoryError("PROMPT_TEMPLATE_NOT_FOUND")
        base = await self.repository.get_version(base_version_id)
        if not base or base.template_id != template_id:
            raise PromptRepositoryError("PROMPT_VERSION_OWNERSHIP")
        try:
            version = await self.repository.create_version(
                template,
                body=payload.get("body", base.body),
                user_prompt_template=payload.get("user_prompt_template", base.user_prompt_template),
                input_schema=payload.get("input_schema", base.input_schema),
                output_schema=payload.get("output_schema", base.output_schema),
                applicability=payload.get("applicability", base.applicability),
                generation_params=payload.get("generation_params", base.generation_params),
                source=payload.get("source", "marketplace"),
                change_note=payload.get("change_note"),
                idempotency_key=idempotency_key
            )
        except PromptRepositoryError as exc:
            if str(exc) == "PROMPT_VERSION_DUPLICATE":
                raise DuplicatePromptVersion from exc
            raise
        # the repository moved default_version_id onto the new version; the
        # template fetched above is a stale snapshot, so re-read it
        refreshed = await self.repository.get_template(template_id)
        return PromptSaveResult(refreshed or template, version)

    async def list_templates(self, stage: str | None = None) -> list[PromptTemplateRecord]:
        return await self.repository.list_templates(stage)

    async def list_categories(self):
        return await self.repository.list_categories()

    async def create_category(self, name: str):
        return await self.repository.create_category(name)

    async def update_category(self, category_id: UUID, name: str):
        return await self.repository.update_category(category_id, name)

    async def delete_category(self, category_id: UUID) -> int:
        return await self.repository.delete_category(category_id)

    async def list_versions(self, template_id: UUID) -> list[PromptVersionRecord]:
        return await self.repository.list_versions(template_id)

    async def list_versions_for_templates(self, template_ids: list[UUID]) -> list[PromptVersionRecord]:
        return await self.repository.list_versions_for_templates(template_ids)

    async def resolve_version(self, template_id: UUID, version_id: UUID | None = None) -> PromptVersionRecord:
        version = await self.repository.resolve_version(template_id, version_id)
        if not version:
            raise PromptRepositoryError("PROMPT_VERSION_NOT_FOUND")
        return version

    async def delete_template(self, template_id: UUID) -> bool:
        """Delete a template and all its versions."""
        result = await self.repository.delete_template(template_id)
        if isinstance(result, bool):
            return result
        return True

    async def update_template(self, template_id: UUID, payload: dict) -> PromptTemplateRecord | None:
        """Update template basic info (name, kind, etc) without creating a new version."""
        return await self.repository.update_template(template_id, payload)

    async def set_default_version(self, template_id: UUID, version_id: UUID) -> PromptTemplateRecord | None:
        """Set the default version for a template."""
        return await self.repository.set_default_version(template_id, version_id)

    async def delete_templates(self, template_ids: list[UUID]) -> list[UUID]:
        """Delete multiple templates and their versions. Returns list of successfully deleted IDs."""
        return await self.repository.delete_templates(template_ids)
