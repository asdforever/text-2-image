import asyncio

from backend.app.migration_baseline import (
    EXPECTED_SCHEMA_COLUMNS,
    EXPECTED_SCHEMAS,
    inspect_existing_schema,
)


class _FakeLegacyConnection:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[str] = []
        self.params: list[object] = []

    async def fetch(self, query, *args):
        self.queries.append(query)
        self.params.extend(args)
        return self.rows


def test_matching_legacy_database_can_be_inspected_without_executing_ddl() -> None:
    rows = [
        {
            "table_schema": schema,
            "table_name": table,
            "column_name": column,
        }
        for schema, table, column in EXPECTED_SCHEMA_COLUMNS
    ]
    connection = _FakeLegacyConnection(rows)

    report = asyncio.run(inspect_existing_schema(connection))

    assert report.compatible is True
    assert report.missing_columns == ()
    assert connection.queries
    assert all(query.lstrip().upper().startswith("SELECT") for query in connection.queries)


def test_schema_inspection_reports_missing_shape_instead_of_replaying_old_ddl() -> None:
    connection = _FakeLegacyConnection([])

    report = asyncio.run(inspect_existing_schema(connection))

    assert report.compatible is False
    assert set(report.missing_columns) == EXPECTED_SCHEMA_COLUMNS


def test_schema_inspection_covers_every_expected_schema() -> None:
    """回归：检查范围必须覆盖 EXPECTED_SCHEMA_COLUMNS 里的全部 schema。

    历史缺陷是过滤条件硬编码为 suite_workbench 和 prompt_library，导致
    project_workbench 的期望列永远查不到，compatible 恒为 False，
    baseline-stamp 被永久拒绝。
    """
    expected_schemas = {schema for schema, _, _ in EXPECTED_SCHEMA_COLUMNS}

    assert set(EXPECTED_SCHEMAS) == expected_schemas
    assert "project_workbench" in EXPECTED_SCHEMAS

    connection = _FakeLegacyConnection([])
    asyncio.run(inspect_existing_schema(connection))

    assert connection.params == [sorted(expected_schemas)]
    assert "project_workbench" in connection.params[0]
