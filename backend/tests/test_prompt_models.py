from uuid import uuid4

from sqlalchemy import inspect

from backend.app.models.base import Base
from backend.app.models.prompt import PromptTemplate, PromptVersion


def test_prompt_models_define_template_and_immutable_version_columns() -> None:
    template = PromptTemplate(code="demo.prompt", name="Demo", kind="planner", stage="plan", execution_target="llm")
    assert template.code == "demo.prompt"
    assert PromptVersion.__tablename__ == "prompt_versions"
    columns = {column.name for column in inspect(PromptVersion).columns}
    assert {"version_no", "content_sha256", "source", "change_note"} <= columns
    assert not {"file_path", "file_sync_status", "file_sync_error", "synced_at"} & columns
    assert PromptVersion.__table__.c.template_id.foreign_keys
    assert any(set(constraint.columns.keys()) == {"template_id", "version_no"} for constraint in PromptVersion.__table__.constraints)
    assert Base.metadata.tables["prompt_library.prompt_templates"] is PromptTemplate.__table__


def test_prompt_version_has_stable_uuid_default() -> None:
    version = PromptVersion(template_id=uuid4(), version_no=1, body="system")
    assert version.body == "system"
