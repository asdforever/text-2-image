from backend.app import migrations


def test_legacy_migration_module_is_read_only_audit_metadata() -> None:
    assert migrations.LEGACY_MIGRATION_TABLE == "schema_migrations"
    assert not hasattr(migrations, "run_migrations")
