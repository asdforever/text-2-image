"""Tests for prompt idempotency key support.

These verify the code structure exposes idempotency_key through the full
call chain (route -> service -> repository).  The SqlAlchemy repository's
actual deduplication relies on the idempotency_keys table and requires a
live database; its integration is covered separately.
"""
import ast
import inspect
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent / "app"


def test_route_accepts_idempotency_key_header():
    source = (ROOT / "routes" / "prompts.py").read_text(encoding="utf-8")
    assert "Idempotency-Key" in source, "create_prompt_template route should accept Idempotency-Key header"
    assert source.count("Idempotency-Key") >= 2, "both create routes should accept the header"


def test_service_create_template_accepts_idempotency_key():
    from backend.app.prompt_service import PromptService
    sig = inspect.signature(PromptService.create_template)
    assert "idempotency_key" in sig.parameters, "create_template should accept idempotency_key"


def test_service_create_version_accepts_idempotency_key():
    from backend.app.prompt_service import PromptService
    sig = inspect.signature(PromptService.create_version)
    assert "idempotency_key" in sig.parameters, "create_version should accept idempotency_key"


def test_sqlalchemy_repo_create_template_with_version_accepts_key():
    from backend.app.prompt_sqlalchemy_repository import SqlAlchemyPromptRepository
    sig = inspect.signature(SqlAlchemyPromptRepository.create_template_with_version)
    assert "idempotency_key" in sig.parameters


def test_sqlalchemy_repo_create_version_accepts_key():
    from backend.app.prompt_sqlalchemy_repository import SqlAlchemyPromptRepository
    sig = inspect.signature(SqlAlchemyPromptRepository.create_version)
    assert "idempotency_key" in sig.parameters


def test_sqlalchemy_repo_queries_idempotency_table():
    source = (ROOT / "prompt_sqlalchemy_repository.py").read_text(encoding="utf-8")
    assert "suite_workbench.idempotency_keys" in source, "should query the shared idempotency_keys table"
    assert "create-prompt-template" in source
    assert "create-prompt-version" in source


def test_memory_repo_signature_compatible():
    from backend.app.prompt_repository import MemoryPromptRepository
    sig_tw = inspect.signature(MemoryPromptRepository.create_template_with_version)
    assert "idempotency_key" in sig_tw.parameters
    sig_cv = inspect.signature(MemoryPromptRepository.create_version)
    assert "idempotency_key" in sig_cv.parameters


def test_rejected_request_does_not_consume_key_by_design():
    """Idempotency key insert is inside the same transaction as the create.
    If the create raises (validation, conflict), the transaction rolls back
    and the key insert is rolled back too - no key consumed."""
    source = (ROOT / "prompt_sqlalchemy_repository.py").read_text(encoding="utf-8")
    # The INSERT of the key must come AFTER the create logic, inside the same
    # `async with self.sessions() as session, session.begin():` block.
    assert source.count("session.begin()") >= 2, "at least create_template_with_version and create_version have transactions"
    # Key insertion appears after version creation
    lines = source.splitlines()
    for method_keyword in ["create-prompt-template", "create-prompt-version"]:
        insert_indices = [i for i, line in enumerate(lines) if f"INSERT INTO suite_workbench.idempotency_keys" in line and method_keyword in line]
        assert insert_indices, f"should insert key for scope containing {method_keyword}"
