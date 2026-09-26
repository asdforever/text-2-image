from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete as sa_delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models.prompt import PromptCategory, PromptTemplate, PromptVersion
from .prompt_repository import PromptCategoryRecord, PromptRepositoryError, PromptTemplateRecord, PromptVersionRecord, prompt_hash


def _template_record(row: PromptTemplate) -> PromptTemplateRecord:
    return PromptTemplateRecord(row.id, row.code, row.name, row.kind, row.kind_name, row.execution_target, row.default_version_id, row.created_at, row.updated_at, row.category_id, row.stage)


def _category_record(row: PromptCategory) -> PromptCategoryRecord:
    return PromptCategoryRecord(row.id, row.name, row.sort_order, row.created_at, row.updated_at)


def _version_record(row: PromptVersion, kind_name: str | None = None) -> PromptVersionRecord:
    # kind_name should come from the associated template, but PromptVersion doesn't store it
    # Use provided kind_name, or try to get from loaded template relationship, or use empty string
    kn = kind_name if kind_name is not None else (row.template.kind_name if hasattr(row, 'template') and row.template else "")
    return PromptVersionRecord(row.id, row.template_id, row.version_no, row.name, row.kind, kn, row.execution_target, row.body, row.user_prompt_template, row.input_schema, row.output_schema, row.applicability, row.generation_params or {}, row.content_sha256, row.source, row.change_note, row.created_by, None, None, None, row.created_at, None)


class SqlAlchemyPromptRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_category(self, name: str) -> PromptCategoryRecord:
        normalized = name.strip()
        if not normalized or len(normalized) > 40:
            raise PromptRepositoryError("PROMPT_CATEGORY_INVALID")
        async with self.sessions() as session, session.begin():
            duplicate = await session.scalar(select(PromptCategory).where(func.lower(PromptCategory.name) == normalized.casefold()))
            if duplicate:
                raise PromptRepositoryError("PROMPT_CATEGORY_CONFLICT")
            max_order = await session.scalar(select(func.max(PromptCategory.sort_order)))
            row = PromptCategory(name=normalized, sort_order=(max_order or -1) + 1)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _category_record(row)

    async def list_categories(self) -> list[PromptCategoryRecord]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(PromptCategory).order_by(PromptCategory.sort_order, PromptCategory.name))).all()
            return [_category_record(row) for row in rows]

    async def get_category(self, category_id: UUID) -> PromptCategoryRecord | None:
        async with self.sessions() as session:
            row = await session.get(PromptCategory, category_id)
            return _category_record(row) if row else None

    async def update_category(self, category_id: UUID, name: str) -> PromptCategoryRecord:
        normalized = name.strip()
        if not normalized or len(normalized) > 40:
            raise PromptRepositoryError("PROMPT_CATEGORY_INVALID")
        async with self.sessions() as session, session.begin():
            row = await session.get(PromptCategory, category_id, with_for_update=True)
            if not row:
                raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
            duplicate = await session.scalar(select(PromptCategory).where(PromptCategory.id != category_id, func.lower(PromptCategory.name) == normalized.casefold()))
            if duplicate:
                raise PromptRepositoryError("PROMPT_CATEGORY_CONFLICT")
            row.name = normalized
            await session.flush()
            await session.refresh(row)
            return _category_record(row)

    async def count_templates_for_category(self, category_id: UUID) -> int:
        async with self.sessions() as session:
            return int(await session.scalar(select(func.count(PromptTemplate.id)).where(PromptTemplate.category_id == category_id)) or 0)

    async def delete_category(self, category_id: UUID) -> int:
        async with self.sessions() as session, session.begin():
            row = await session.get(PromptCategory, category_id, with_for_update=True)
            if not row:
                raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
            affected = int(await session.scalar(select(func.count(PromptTemplate.id)).where(PromptTemplate.category_id == category_id)) or 0)
            await session.execute(update(PromptTemplate).where(PromptTemplate.category_id == category_id).values(category_id=None))
            await session.execute(sa_delete(PromptCategory).where(PromptCategory.id == category_id))
            return affected

    async def create_template(self, *, code: str, name: str, kind: str, kind_name: str, execution_target: str, category_id: UUID | None = None, stage: str = "plan") -> PromptTemplateRecord:
        async with self.sessions() as session, session.begin():
            existing = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
            if existing:
                raise PromptRepositoryError("PROMPT_CODE_CONFLICT")
            if category_id is not None and not await session.get(PromptCategory, category_id):
                raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
            row = PromptTemplate(code=code, name=name, kind=kind, kind_name=kind_name, stage=stage, execution_target=execution_target, category_id=category_id)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _template_record(row)

    async def create_template_with_version(self, *, code: str, name: str, kind: str, kind_name: str, execution_target: str, body: str, user_prompt_template: str = "", input_schema: list | None = None, output_schema: dict | None = None, applicability: dict | None = None, generation_params: dict | None = None, source: str = "marketplace", change_note: str | None = None, idempotency_key: str | None = None, category_id: UUID | None = None, stage: str = "plan") -> tuple[PromptTemplateRecord, PromptVersionRecord]:
        input_schema, output_schema, applicability, generation_params = input_schema or [], output_schema or {}, applicability or {}, generation_params or {}
        digest = prompt_hash({"name": name, "body": body, "user_prompt_template": user_prompt_template, "input_schema": input_schema, "output_schema": output_schema, "applicability": applicability, "generation_params": generation_params})
        async with self.sessions() as session, session.begin():
            if idempotency_key:
                existing = await session.execute(text("SELECT resource_id FROM suite_workbench.idempotency_keys WHERE scope=:scope AND key=:key"), {"scope": "create-prompt-template", "key": idempotency_key})
                row_idem = existing.first()
                if row_idem:
                    tmpl = await session.get(PromptTemplate, row_idem[0])
                    if tmpl:
                        ver = await session.scalar(select(PromptVersion).where(PromptVersion.template_id == tmpl.id).order_by(PromptVersion.version_no.desc()).limit(1))
                        if ver:
                            return _template_record(tmpl), _version_record(ver, tmpl.kind_name)
            existing = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
            if existing:
                raise PromptRepositoryError("PROMPT_CODE_CONFLICT")
            if category_id is not None and not await session.get(PromptCategory, category_id):
                raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
            template = PromptTemplate(code=code, name=name, kind=kind, kind_name=kind_name, stage=stage, execution_target=execution_target, category_id=category_id)
            session.add(template)
            await session.flush()
            version = PromptVersion(template_id=template.id, version_no=1, name=name, kind=kind, execution_target=execution_target, body=body, user_prompt_template=user_prompt_template, input_schema=input_schema, output_schema=output_schema, applicability=applicability, generation_params=generation_params, content_sha256=digest, source=source, change_note=change_note, created_by="local-user")
            session.add(version)
            await session.flush()
            template.default_version_id = version.id
            await session.flush()
            if idempotency_key:
                await session.execute(text("INSERT INTO suite_workbench.idempotency_keys(scope,key,resource_id) VALUES (:scope,:key,:id)"), {"scope": "create-prompt-template", "key": idempotency_key, "id": template.id})
            await session.refresh(template)
            await session.refresh(version)
            return _template_record(template), _version_record(version, kind_name)

    async def get_template(self, template_id: UUID) -> PromptTemplateRecord | None:
        async with self.sessions() as session:
            row = await session.get(PromptTemplate, template_id)
            return _template_record(row) if row else None

    async def get_template_by_code(self, code: str) -> PromptTemplateRecord | None:
        async with self.sessions() as session:
            row = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
            return _template_record(row) if row else None

    async def list_templates(self, stage: str | None = None) -> list[PromptTemplateRecord]:
        async with self.sessions() as session:
            statement = select(PromptTemplate).order_by(PromptTemplate.name)
            if stage is not None:
                statement = statement.where(PromptTemplate.stage == stage)
            rows = (await session.scalars(statement)).all()
            return [_template_record(row) for row in rows]

    async def create_version(self, template: PromptTemplateRecord, *, body: str, user_prompt_template: str = "", input_schema: list | None = None, output_schema: dict | None = None, applicability: dict | None = None, generation_params: dict | None = None, source: str = "marketplace", change_note: str | None = None, created_by: str = "local-user", version_no: int | None = None, content_sha256: str | None = None, idempotency_key: str | None = None) -> PromptVersionRecord:
        input_schema, output_schema, applicability, generation_params = input_schema or [], output_schema or {}, applicability or {}, generation_params or {}
        digest = content_sha256 or prompt_hash({"name": template.name, "body": body, "user_prompt_template": user_prompt_template, "input_schema": input_schema, "output_schema": output_schema, "applicability": applicability, "generation_params": generation_params})
        async with self.sessions() as session, session.begin():
            if idempotency_key:
                scope = f"create-prompt-version:{template.id}"
                existing = await session.execute(text("SELECT resource_id FROM suite_workbench.idempotency_keys WHERE scope=:scope AND key=:key"), {"scope": scope, "key": idempotency_key})
                row_idem = existing.first()
                if row_idem:
                    ver = await session.get(PromptVersion, row_idem[0])
                    if ver:
                        return _version_record(ver, template.kind_name)
            locked = await session.scalar(select(PromptTemplate).where(PromptTemplate.id == template.id).with_for_update())
            if not locked:
                raise PromptRepositoryError("PROMPT_TEMPLATE_NOT_FOUND")
            duplicate = await session.scalar(select(PromptVersion).where(PromptVersion.template_id == template.id, PromptVersion.content_sha256 == digest))
            if duplicate:
                raise PromptRepositoryError("PROMPT_VERSION_DUPLICATE")
            if version_no is None:
                latest = await session.scalar(select(PromptVersion.version_no).where(PromptVersion.template_id == template.id).order_by(PromptVersion.version_no.desc()).limit(1))
                version_no = (latest or 0) + 1
            row = PromptVersion(template_id=template.id, version_no=version_no, name=locked.name, kind=locked.kind, execution_target=locked.execution_target, body=body, user_prompt_template=user_prompt_template, input_schema=input_schema, output_schema=output_schema, applicability=applicability, generation_params=generation_params, content_sha256=digest, source=source, change_note=change_note, created_by=created_by)
            session.add(row)
            await session.flush()
            locked.default_version_id = row.id
            await session.flush()
            if idempotency_key:
                await session.execute(text("INSERT INTO suite_workbench.idempotency_keys(scope,key,resource_id) VALUES (:scope,:key,:id)"), {"scope": f"create-prompt-version:{template.id}", "key": idempotency_key, "id": row.id})
            await session.refresh(row)
            return _version_record(row, locked.kind_name)

    async def get_version(self, version_id: UUID) -> PromptVersionRecord | None:
        async with self.sessions() as session:
            row = await session.get(PromptVersion, version_id)
            if not row:
                return None
            # Load the template to get kind_name
            template = await session.get(PromptTemplate, row.template_id)
            return _version_record(row, template.kind_name if template else "")

    async def list_versions(self, template_id: UUID) -> list[PromptVersionRecord]:
        async with self.sessions() as session:
            template = await session.get(PromptTemplate, template_id)
            if not template:
                return []
            rows = (await session.scalars(select(PromptVersion).where(PromptVersion.template_id == template_id).order_by(PromptVersion.version_no))).all()
            return [_version_record(row, template.kind_name) for row in rows]

    async def list_versions_for_templates(self, template_ids: list[UUID]) -> list[PromptVersionRecord]:
        if not template_ids:
            return []
        async with self.sessions() as session:
            statement = (
                select(PromptVersion, PromptTemplate.kind_name)
                .join(PromptTemplate, PromptTemplate.id == PromptVersion.template_id)
                .where(PromptVersion.template_id.in_(template_ids))
                .order_by(PromptVersion.version_no)
            )
            rows = (await session.execute(statement)).all()
            return [_version_record(version, kind_name) for version, kind_name in rows]

    async def resolve_version(self, template_id: UUID, version_id: UUID | None = None) -> PromptVersionRecord | None:
        async with self.sessions() as session:
            template = await session.get(PromptTemplate, template_id)
            if not template:
                return None
            if version_id is not None:
                row = await session.get(PromptVersion, version_id)
                if not row or row.template_id != template_id:
                    raise PromptRepositoryError("PROMPT_VERSION_OWNERSHIP")
                return _version_record(row, template.kind_name)
            row = await session.get(PromptVersion, template.default_version_id) if template.default_version_id else None
            return _version_record(row, template.kind_name) if row else None

    async def mark_sync(self, version_id: UUID, *, status: str, path: str | None = None, error: str | None = None) -> PromptVersionRecord | None:
        async with self.sessions() as session, session.begin():
            row = await session.get(PromptVersion, version_id, with_for_update=True)
            if not row:
                return None
            row.file_sync_status = status
            row.file_sync_error = error
            if path:
                row.file_path = path
            row.synced_at = datetime.now(timezone.utc) if status == "synced" else None
            await session.flush()
            # Load template to get kind_name
            template = await session.get(PromptTemplate, row.template_id)
            return _version_record(row, template.kind_name if template else "")

    async def delete_template(self, template_id: UUID) -> PromptTemplateRecord | None:
        """Delete a template and all its versions (CASCADE). Returns the deleted template record or None."""
        async with self.sessions() as session, session.begin():
            row = await session.get(PromptTemplate, template_id)
            if not row:
                return None
            record = _template_record(row)
            # Use raw DELETE to avoid ORM cascade conflicts with DB-level ON DELETE CASCADE
            await session.execute(sa_delete(PromptVersion).where(PromptVersion.template_id == template_id))
            await session.execute(sa_delete(PromptTemplate).where(PromptTemplate.id == template_id))
            return record

    async def update_template(self, template_id: UUID, payload: dict) -> PromptTemplateRecord | None:
        """Update template basic info (name, kind_name) without creating a new version."""
        async with self.sessions() as session, session.begin():
            row = await session.get(PromptTemplate, template_id)
            if not row:
                return None

            if "name" in payload:
                row.name = payload["name"]
            if "kindName" in payload:
                row.kind_name = payload["kindName"]
            if "categoryId" in payload:
                category_id = payload["categoryId"]
                if category_id is not None and not await session.get(PromptCategory, category_id):
                    raise PromptRepositoryError("PROMPT_CATEGORY_NOT_FOUND")
                row.category_id = category_id

            row.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await session.refresh(row)
            return _template_record(row)

    async def set_default_version(self, template_id: UUID, version_id: UUID) -> PromptTemplateRecord | None:
        """Set the default version for a template."""
        async with self.sessions() as session, session.begin():
            template = await session.get(PromptTemplate, template_id)
            if not template:
                return None

            # Verify the version exists and belongs to this template
            version = await session.get(PromptVersion, version_id)
            if not version or version.template_id != template_id:
                return None

            template.default_version_id = version_id
            template.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await session.refresh(template)
            return _template_record(template)

    async def delete_templates(self, template_ids: list[UUID]) -> list[UUID]:
        """Delete multiple templates. Returns list of successfully deleted IDs."""
        deleted: list[UUID] = []
        for template_id in template_ids:
            result = await self.delete_template(template_id)
            if result is not None:
                deleted.append(template_id)
        return deleted
