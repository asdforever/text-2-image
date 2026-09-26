from pathlib import Path

import asyncio
import ast
import logging

import httpx

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def test_backend_sources_are_utf8_and_example_has_no_secret_values() -> None:
    root = Path(__file__).parents[2]
    for path in (root / "backend").rglob("*.py"):
        path.read_text(encoding="utf-8")
    example = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    assert "sk-" not in example
    assert "password@" in example


def test_backend_has_no_debug_routes_prints_or_stack_logging() -> None:
    root = Path(__file__).parents[2]
    source_files = list((root / "backend" / "app").rglob("*.py"))
    sources = [path.read_text(encoding="utf-8") for path in source_files]
    combined = "\n".join(sources)
    calls = [
        node.func
        for source in sources
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
    ]

    assert not any(isinstance(call, ast.Name) and call.id == "print" for call in calls)
    assert not any(
        isinstance(call, ast.Attribute)
        and isinstance(call.value, ast.Name)
        and call.value.id == "logger"
        and call.attr == "exception"
        for call in calls
    )
    assert "error_message=str(" not in combined
    assert "Failed to upload file: {exc}" not in combined

    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
    )
    paths = app.openapi()["paths"]
    assert "/api/debug-body" not in paths
    assert "/api/test-json" not in paths
    assert "/api/test-pydantic" not in paths


def test_unhandled_error_log_contains_request_id_but_not_internal_details(caplog) -> None:
    secret = "postgresql://user:password@db/private-bucket/object-key"

    class BrokenAssetService:
        async def list_libraries(self):
            raise RuntimeError(secret)

    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            asset_service=BrokenAssetService(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/asset-libraries",
                headers={"X-Request-ID": "security-request-1"},
            )
        assert response.status_code == 500

    with caplog.at_level(logging.ERROR, logger="picagent"):
        asyncio.run(run())

    records = [record for record in caplog.records if record.name == "picagent"]
    assert records
    assert records[-1].request_id == "security-request-1"
    rendered = caplog.text
    for forbidden in ("password", "private-bucket", "object-key", "Traceback"):
        assert forbidden not in rendered
