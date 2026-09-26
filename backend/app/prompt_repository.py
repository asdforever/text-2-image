from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4


class PromptRepositoryError(RuntimeError):
    pass


@dataclass
class PromptCategoryRecord:
    id: UUID
    name: str
    sort_order: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PromptTemplateRecord:
    id: UUID
    code: str
    name: str
    kind: str
    kind_name: str
    execution_target: str
    default_version_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    category_id: UUID | None = None
    stage: str = "plan"


@dataclass
class PromptVersionRecord:
    id: UUID
    template_id: UUID
    version_no: int
    name: str
    kind: str
    kind_name: str
    execution_target: str
    body: str
    user_prompt_template: str
    input_schema: list
    output_schema: dict
    applicability: dict
    generation_params: dict = field(default_factory=dict)
    content_sha256: str = ""
    source: str = "marketplace"
    change_note: str | None = None
    created_by: str = "local-user"
    file_path: str = ""
    file_sync_status: str = "pending"
    file_sync_error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    synced_at: datetime | None = None


def prompt_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class MemoryPromptRepository:
    def __init__(self) -> None:
        self.templates: dict[UUID, PromptTemplateRecord] = {}
        self.versions: dict[UUID, PromptVersionRecord] = {}
        self.categories: dict[UUID, PromptCategoryRecord] = {}

    @staticmethod
    def _category_name(value: str) -> str:
        name = value.strip()
        if not name or len(name) > 40:
            raise PromptRepositoryError("PROMPT_CATEGORY_INVALID")
        return name

    async def create_category(self, name: str) -> PromptCategoryRecord:
        normalized = self._category_name(name)
        if any(item.name.casefold() == normalized.casefold() for item in self.categories.values()):
            raise PromptRepositoryError("PROMPT_CATEGORY_CONFLICT")
        record = PromptCategoryRecord(uuid4(), normalized, len(self.categories))
        self.categories[record.id] = record
        return record

    async def list_categories(self) -> list[PromptCategoryRecord]:
        return sorted(self.categories.values(), key=lambda item: (item.sort_order, item.name.casefold()))

    async def get_category(self, category_id: UUID) -> PromptCategoryRecord | None:
        return self.categories.get(category_id)

    async def update_category(self, category_id: UUID, name: str) -> PromptCategoryRecord:
        category = self.categories.get(category_id)
        if not category:
            raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
        normalized = self._category_name(name)
        if any(item.id != category_id and item.name.casefold() == normalized.casefold() for item in self.categories.values()):
            raise PromptRepositoryError("PROMPT_CATEGORY_CONFLICT")
        category.name = normalized
        category.updated_at = datetime.now(timezone.utc)
        return category

    async def count_templates_for_category(self, category_id: UUID) -> int:
        return sum(1 for item in self.templates.values() if item.category_id == category_id)

    async def delete_category(self, category_id: UUID) -> int:
        if category_id not in self.categories:
            raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
        affected = await self.count_templates_for_category(category_id)
        for template in self.templates.values():
            if template.category_id == category_id:
                template.category_id = None
        del self.categories[category_id]
        return affected

    async def create_template(self, *, code: str, name: str, kind: str, kind_name: str, execution_target: str, category_id: UUID | None = None, stage: str = "plan") -> PromptTemplateRecord:
        if any(item.code == code for item in self.templates.values()):
            raise PromptRepositoryError("PROMPT_CODE_CONFLICT")
        if category_id is not None and category_id not in self.categories:
            raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
        record = PromptTemplateRecord(uuid4(), code, name, kind, kind_name, execution_target, category_id=category_id, stage=stage)
        self.templates[record.id] = record
        return record

    async def create_template_with_version(self, *, code: str, name: str, kind: str, kind_name: str, execution_target: str, body: str, user_prompt_template: str = "", input_schema: list | None = None, output_schema: dict | None = None, applicability: dict | None = None, generation_params: dict | None = None, source: str = "marketplace", change_note: str | None = None, idempotency_key: str | None = None, category_id: UUID | None = None, stage: str = "plan") -> tuple[PromptTemplateRecord, PromptVersionRecord]:
        template = await self.create_template(code=code, name=name, kind=kind, kind_name=kind_name, execution_target=execution_target, category_id=category_id, stage=stage)
        try:
            version = await self.create_version(template, body=body, user_prompt_template=user_prompt_template, input_schema=input_schema, output_schema=output_schema, applicability=applicability, generation_params=generation_params, source=source, change_note=change_note)
        except Exception:
            self.templates.pop(template.id, None)
            raise
        return template, version

    async def get_template(self, template_id: UUID) -> PromptTemplateRecord | None:
        return self.templates.get(template_id)

    async def get_template_by_code(self, code: str) -> PromptTemplateRecord | None:
        return next((item for item in self.templates.values() if item.code == code), None)

    async def list_templates(self, stage: str | None = None) -> list[PromptTemplateRecord]:
        values = self.templates.values() if stage is None else (item for item in self.templates.values() if item.stage == stage)
        return sorted(values, key=lambda item: item.name.lower())

    async def create_version(self, template: PromptTemplateRecord, *, body: str, user_prompt_template: str = "", input_schema: list | None = None, output_schema: dict | None = None, applicability: dict | None = None, generation_params: dict | None = None, source: str = "marketplace", change_note: str | None = None, created_by: str = "local-user", version_no: int | None = None, content_sha256: str | None = None, idempotency_key: str | None = None) -> PromptVersionRecord:
        input_schema = input_schema or []
        output_schema = output_schema or {}
        applicability = applicability or {}
        generation_params = generation_params or {}
        digest = content_sha256 or prompt_hash({"name": template.name, "body": body, "user_prompt_template": user_prompt_template, "input_schema": input_schema, "output_schema": output_schema, "applicability": applicability, "generation_params": generation_params})
        if any(item.template_id == template.id and item.content_sha256 == digest for item in self.versions.values()):
            raise PromptRepositoryError("PROMPT_VERSION_DUPLICATE")
        number = version_no or (max((item.version_no for item in self.versions.values() if item.template_id == template.id), default=0) + 1)
        record = PromptVersionRecord(uuid4(), template.id, number, template.name, template.kind, template.kind_name, template.execution_target, body, user_prompt_template, input_schema, output_schema, applicability, generation_params, digest, source, change_note, created_by, "", "synced")
        self.versions[record.id] = record
        template.default_version_id = record.id
        template.updated_at = datetime.now(timezone.utc)
        return record

    async def get_version(self, version_id: UUID) -> PromptVersionRecord | None:
        return self.versions.get(version_id)

    async def list_versions(self, template_id: UUID) -> list[PromptVersionRecord]:
        return sorted((item for item in self.versions.values() if item.template_id == template_id), key=lambda item: item.version_no)

    async def list_versions_for_templates(self, template_ids: list[UUID]) -> list[PromptVersionRecord]:
        requested = set(template_ids)
        return sorted(
            (item for item in self.versions.values() if item.template_id in requested),
            key=lambda item: item.version_no,
        )

    async def resolve_version(self, template_id: UUID, version_id: UUID | None = None) -> PromptVersionRecord | None:
        template = self.templates.get(template_id)
        if not template:
            return None
        if version_id is not None:
            version = self.versions.get(version_id)
            if not version or version.template_id != template_id:
                raise PromptRepositoryError("PROMPT_VERSION_OWNERSHIP")
            return version
        return self.versions.get(template.default_version_id) if template.default_version_id else None

    async def delete_template(self, template_id: UUID) -> bool:
        """Delete a template and all its versions."""
        template = self.templates.get(template_id)
        if not template:
            return False
        # Delete all versions associated with this template
        version_ids = [vid for vid, v in self.versions.items() if v.template_id == template_id]
        for vid in version_ids:
            del self.versions[vid]
        # Delete the template
        del self.templates[template_id]
        return True

    async def delete_templates(self, template_ids: list[UUID]) -> list[UUID]:
        """Delete multiple templates and their versions. Returns list of successfully deleted IDs."""
        deleted = []
        for template_id in template_ids:
            if await self.delete_template(template_id):
                deleted.append(template_id)
        return deleted

    async def update_template(self, template_id: UUID, payload: dict) -> PromptTemplateRecord | None:
        template = self.templates.get(template_id)
        if not template:
            return None
        if "name" in payload:
            template.name = payload["name"]
        if "kindName" in payload:
            template.kind_name = payload["kindName"]
        if "categoryId" in payload:
            category_id = payload["categoryId"]
            if category_id is not None and category_id not in self.categories:
                raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
            template.category_id = category_id
        template.updated_at = datetime.now(timezone.utc)
        return template
