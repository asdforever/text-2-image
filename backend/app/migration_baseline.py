"""已有数据库的只读结构识别，用于一次性 Alembic 基线登记。"""

from dataclasses import dataclass


EXPECTED_SCHEMA_COLUMNS: set[tuple[str, str, str]] = {
    ("project_workbench", "generation_worker_heartbeats", "last_seen_at"),
    ("suite_workbench", "workspaces", "id"),
    ("suite_workbench", "suites", "workspace_id"),
    ("suite_workbench", "input_images", "original_object_key"),
    ("suite_workbench", "idempotency_keys", "request_fingerprint"),
    ("suite_workbench", "idempotency_keys", "response_body"),
    ("prompt_library", "prompt_templates", "kind_name"),
    ("prompt_library", "prompt_templates", "category_id"),
    ("prompt_library", "prompt_versions", "generation_params"),
    ("prompt_library", "asset_libraries", "id"),
    ("prompt_library", "assets", "library_id"),
    ("prompt_library", "product_libraries", "id"),
    ("prompt_library", "products", "library_id"),
    ("prompt_library", "test_runs", "prompt_version_id"),
    ("prompt_library", "prompt_categories", "id"),
    ("project_workbench", "image_edit_sessions", "id"),
    ("project_workbench", "image_edit_operations", "session_id"),
    ("project_workbench", "image_ocr_results", "session_id"),
    ("project_workbench", "image_edit_tasks", "id"),
    ("project_workbench", "image_edit_attempts", "task_id"),
    ("project_workbench", "image_edit_versions", "task_id"),
    ("project_workbench", "product_libraries", "id"),
    ("project_workbench", "products", "library_id"),
    ("project_workbench", "product_versions", "product_id"),
}

# 检查范围从 EXPECTED_SCHEMA_COLUMNS 派生，避免新增 schema 后过滤条件漏掉它。
# 之前的硬编码只覆盖 suite_workbench 和 prompt_library，导致 project_workbench
# 的期望列永远查不到，compatible 恒为 False，baseline-stamp 被永久拒绝。
EXPECTED_SCHEMAS: tuple[str, ...] = tuple(
    sorted({schema for schema, _, _ in EXPECTED_SCHEMA_COLUMNS})
)


@dataclass(frozen=True, slots=True)
class SchemaCompatibilityReport:
    compatible: bool
    missing_columns: tuple[tuple[str, str, str], ...]


async def inspect_existing_schema(connection) -> SchemaCompatibilityReport:
    """只读检查当前 head 所需的关键结构，不创建或修改任何对象。"""
    rows = await connection.fetch(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY($1::text[])
        """,
        list(EXPECTED_SCHEMAS),
    )
    actual = {
        (row["table_schema"], row["table_name"], row["column_name"])
        for row in rows
    }
    missing = tuple(sorted(EXPECTED_SCHEMA_COLUMNS - actual))
    return SchemaCompatibilityReport(not missing, missing)
