import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from backend.app.models.prompt import PromptTemplate, PromptVersion
from backend.app.prompt_sqlalchemy_repository import SqlAlchemyPromptRepository


def test_sqlalchemy_prompt_repository_exposes_version_operations() -> None:
    expected = {
        "create_template",
        "create_template_with_version",
        "get_template",
        "list_templates",
        "create_version",
        "get_version",
        "list_versions",
        "resolve_version",
        "mark_sync",
    }
    assert expected <= set(dir(SqlAlchemyPromptRepository))


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def scalar(self, _statement):
        return None

    async def get(self, _model, _identity):
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, (PromptTemplate, PromptVersion)) and value.id is None:
                value.id = uuid4()

    async def refresh(self, _value: object) -> None:
        return None

    @asynccontextmanager
    async def begin(self):
        yield self


class _FakeSessions:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def __call__(self):
        yield self.session


def test_sqlalchemy_prompt_creation_matches_current_prompt_version_schema() -> None:
    async def run() -> None:
        session = _FakeSession()
        repository = SqlAlchemyPromptRepository(_FakeSessions(session))

        template, version = await repository.create_template_with_version(
            code="regression.prompt",
            name="回归提示词",
            kind="text_to_image",
            kind_name="文生图",
            execution_target="api",
            body="生成一张测试图片",
        )

        assert isinstance(template.id, UUID)
        assert isinstance(version.id, UUID)
        assert version.version_no == 1
        assert version.file_path is None
        assert version.file_sync_status is None

    asyncio.run(run())


def test_sqlalchemy_prompt_versions_batch_uses_one_query() -> None:
    async def run() -> None:
        template_ids = [uuid4(), uuid4()]
        rows = [
            (PromptVersion(
                id=uuid4(), template_id=template_id, version_no=number, name="Prompt",
                kind="planner", execution_target="llm", body=f"body {number}",
                user_prompt_template="user", input_schema=[], output_schema={},
                applicability={}, generation_params={}, content_sha256="digest",
                source="marketplace", change_note=None, created_by="local-user",
                created_at=datetime.now(timezone.utc),
            ), kind_name)
            for template_id, number, kind_name in [
                (template_ids[0], 1, "First kind"),
                (template_ids[1], 1, "Second kind"),
                (template_ids[0], 2, "First kind"),
            ]
        ]

        class BatchSession(_FakeSession):
            def __init__(self):
                super().__init__()
                self.statements = []

            async def execute(self, statement):
                self.statements.append(statement)
                return SimpleNamespace(all=lambda: rows)

            async def get(self, *_args):
                raise AssertionError("batch version reads must not query individual templates")

        session = BatchSession()
        repository = SqlAlchemyPromptRepository(_FakeSessions(session))
        assert hasattr(repository, "list_versions_for_templates"), "batch version reads are required"
        versions = await repository.list_versions_for_templates(template_ids)
        assert len(session.statements) == 1
        assert [(item.template_id, item.version_no, item.kind_name) for item in versions] == [
            (template_ids[0], 1, "First kind"),
            (template_ids[1], 1, "Second kind"),
            (template_ids[0], 2, "First kind"),
        ]
        assert [item.body for item in versions] == ["body 1", "body 1", "body 2"]
        # Validate the emitted query is scoped to the requested templates.
        compiled = session.statements[0].compile()
        assert template_ids in compiled.params.values()
        assert "ORDER BY prompt_library.prompt_versions.version_no" in str(compiled)
        assert await repository.list_versions_for_templates([]) == []
        assert len(session.statements) == 1

    asyncio.run(run())
