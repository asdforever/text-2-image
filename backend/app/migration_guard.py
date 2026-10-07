"""Alembic 执行前的数据库锁与 revision 校验和保护。"""

import hashlib
from pathlib import Path
from typing import Awaitable, Callable

from alembic.script import ScriptDirectory


class MigrationDriftError(RuntimeError):
    pass


EXPECTED_ALEMBIC_HEAD = "20260930_reverse_execution"


def revision_checksums(script: ScriptDirectory) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for revision in script.walk_revisions():
        path = Path(revision.path)
        checksums[revision.revision] = hashlib.sha256(path.read_bytes()).hexdigest()
    return checksums


async def run_guarded_migration(
    connection,
    expected: dict[str, str],
    migrate: Callable[[], Awaitable[None]],
    *,
    checksum_table_exists: bool,
) -> None:
    await connection.execute(
        "SELECT pg_advisory_lock(hashtext('picagent:alembic:migrate'))"
    )
    try:
        if checksum_table_exists:
            rows = await connection.fetch(
                "SELECT revision, checksum FROM "
                "suite_workbench.migration_revision_checksums"
            )
            for row in rows:
                actual = expected.get(row["revision"])
                if actual != row["checksum"]:
                    raise MigrationDriftError(
                        f"已执行的 Alembic revision 校验和不匹配：{row['revision']}"
                    )
        await migrate()
        await connection.executemany(
            "INSERT INTO suite_workbench.migration_revision_checksums "
            "(revision, checksum) VALUES ($1, $2) "
            "ON CONFLICT (revision) DO NOTHING",
            sorted(expected.items()),
        )
    finally:
        await connection.execute(
            "SELECT pg_advisory_unlock(hashtext('picagent:alembic:migrate'))"
        )
