from pathlib import Path

from backend.app.core.boundary_check import find_route_boundary_violations


ROUTE_FILES = [
    Path("backend/app/routes/projects.py"),
    Path("backend/app/routes/assets.py"),
    Path("backend/app/routes/products.py"),
    Path("backend/app/routes/test_runs.py"),
]


def test_migrated_routes_do_not_access_database_or_storage_adapters() -> None:
    violations = []
    for path in ROUTE_FILES:
        violations.extend(
            find_route_boundary_violations(path.read_text(encoding="utf-8"), str(path))
        )
    assert violations == []


def test_boundary_check_rejects_a_deliberate_route_violation() -> None:
    source = """
from sqlalchemy import select

async def broken_route(request):
    session = request.app.state.db_session
    await request.app.state.asset_storage.delete_file("secret-key")
"""
    violations = find_route_boundary_violations(source, "broken_route.py")

    assert len(violations) >= 3
    assert any("sqlalchemy" in item for item in violations)
    assert any("db_session" in item for item in violations)
    assert any("asset_storage" in item for item in violations)
