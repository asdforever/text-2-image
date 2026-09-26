from pathlib import Path


def test_checksum_audit_table_is_created_by_alembic() -> None:
    source = Path(
        "alembic/versions/e5f6a7b8c9d0_add_migration_revision_checksums.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "d4e5f6a7b8c9"' in source
    assert "migration_revision_checksums" in source
    assert "revision" in source
    assert "checksum" in source
