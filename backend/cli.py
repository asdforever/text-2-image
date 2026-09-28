import argparse
import asyncio
import json
import logging
from uuid import uuid4

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .app.core.config import Settings, get_settings
from .app.prompt_service import PromptService
from .app.prompt_sqlalchemy_repository import SqlAlchemyPromptRepository
from .app.db import create_engine, create_session_factory
from .app.migration_baseline import inspect_existing_schema
from .app.migration_guard import revision_checksums, run_guarded_migration
from .app.main import create_app
from .app.application.batch_generation_worker import BatchGenerationWorker
from .app.application.project_archive_service import ProjectArchiveBackfillService
from .app.generation_worker_health import keep_worker_alive

logger = logging.getLogger(__name__)


def _alembic_config() -> Config:
    return Config("alembic.ini")


def migrate() -> None:
    """Apply all root-project Alembic migrations."""
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for migrations")
    config = _alembic_config()
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    expected = revision_checksums(ScriptDirectory.from_config(config))

    async def run() -> None:
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(dsn)
        try:
            table_exists = await connection.fetchval(
                "SELECT to_regclass('suite_workbench.migration_revision_checksums') IS NOT NULL"
            )

            async def upgrade() -> None:
                await asyncio.to_thread(command.upgrade, config, "head")

            await run_guarded_migration(
                connection,
                expected,
                upgrade,
                checksum_table_exists=bool(table_exists),
            )
        finally:
            await connection.close()

    asyncio.run(run())


async def _inspect_configured_schema(settings: Settings):
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for schema inspection")
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        return await inspect_existing_schema(connection)
    finally:
        await connection.close()


def schema_check() -> None:
    report = asyncio.run(_inspect_configured_schema(get_settings()))
    print(
        json.dumps(
            {
                "compatible": report.compatible,
                "missingColumns": [".".join(item) for item in report.missing_columns],
            },
            ensure_ascii=False,
        )
    )


def baseline_stamp(confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("baseline-stamp requires --confirm-baseline")
    settings = get_settings()
    report = asyncio.run(_inspect_configured_schema(settings))
    if not report.compatible:
        missing = ", ".join(".".join(item) for item in report.missing_columns)
        raise SystemExit(f"Schema does not match current Alembic head; missing: {missing}")
    config = _alembic_config()
    config.set_main_option("sqlalchemy.url", (settings.database_url or "").replace("%", "%%"))
    command.stamp(config, "head")


def _assert_reset_allowed(settings: Settings, confirmed: bool) -> None:
    if settings.environment.lower() != "development":
        raise SystemExit("db-reset is only allowed when ENVIRONMENT=development")
    if not confirmed:
        raise SystemExit("db-reset requires --confirm-reset")
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for db-reset")


APPLICATION_SCHEMAS: tuple[str, ...] = (
    "project_workbench",
    "generation_config",
    "suite_workbench",
    "prompt_library",
)


async def _drop_application_schemas(database_url: str) -> None:
    """删除全部应用 schema 与 Alembic 版本表。

    必须覆盖 migrations 创建过的每一个 schema（0001_initial 建立 suite_workbench
    和 prompt_library，a7b8c9d0e1f2 建立 generation_config，f6a7b8c9d0e1 建立
    project_workbench）。漏掉任何一个，后续 migrate() 都会在 CREATE SCHEMA 或
    CREATE TABLE 上因对象已存在而失败。
    """
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        for schema in APPLICATION_SCHEMAS:
            await connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await connection.execute("DROP TABLE IF EXISTS public.alembic_version CASCADE")
    finally:
        await connection.close()


def db_reset(confirmed: bool) -> None:
    settings = get_settings()
    _assert_reset_allowed(settings, confirmed)
    asyncio.run(_drop_application_schemas(settings.database_url or ""))
    migrate()


def generation_worker(once: bool) -> None:
    """执行已确认批次中的图片槽位。"""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("backend.app.application.batch_generation_worker").setLevel(logging.INFO)
    async def run() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            settings = app.state.settings
            worker = BatchGenerationWorker(
                repository=app.state.batch_generation_repository,
                project_repository=app.state.project_repository,
                project_storage=app.state.project_asset_storage,
                project_asset_service=app.state.project_asset_service,
                image_editor=app.state.hero_generation_service.image_editor,
                project_output_archive=app.state.product_library_service,
                worker_id="generation-worker",
                lease_seconds=settings.generation_worker_lease_seconds,
                concurrency=settings.generation_worker_concurrency,
                provider_timeout_seconds=getattr(settings, "image_generation_timeout_ms", 600000) / 1000,
            )
            async with keep_worker_alive(app.state.generation_worker_health, str(uuid4())):
                while True:
                    try:
                        await app.state.batch_generation_repository.recover_expired_leases()
                        completed = await worker.run_once(
                            limit=settings.generation_worker_claim_limit, raise_on_error=once,
                            refill=not once,
                            poll_interval=settings.generation_worker_poll_interval_ms / 1000,
                        )
                    except Exception as exc:
                        if once:
                            raise
                        # 不记录异常正文，以免数据库/Provider 异常泄露连接凭据。
                        logger.warning("生图执行器本轮失败 (%s)，稍后重试", type(exc).__name__)
                        await asyncio.sleep(max(1.0, settings.generation_worker_poll_interval_ms / 1000))
                        continue
                    if once:
                        print(json.dumps({"completed": completed}, ensure_ascii=False))
                        return
                    if completed == 0:
                        await asyncio.sleep(settings.generation_worker_poll_interval_ms / 1000)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


def project_archive_backfill(page_size: int) -> None:
    """为已有项目和项目资产补齐正式成品档案关系。"""

    async def run() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            service = ProjectArchiveBackfillService(
                app.state.project_repository,
                app.state.project_archive,
                app.state.identity_provider,
            )
            report = await service.backfill_workspace(page_size=page_size)
            print(json.dumps(report.__dict__, ensure_ascii=False))

    asyncio.run(run())


def main() -> None:
    parser = argparse.ArgumentParser(prog="picagent-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    subparsers.add_parser("schema-check")
    baseline = subparsers.add_parser("baseline-stamp")
    baseline.add_argument("--confirm-baseline", action="store_true")
    reset = subparsers.add_parser("db-reset")
    reset.add_argument("--confirm-reset", action="store_true")
    worker = subparsers.add_parser("generation-worker")
    worker.add_argument("--once", action="store_true")
    backfill = subparsers.add_parser("project-archive-backfill")
    backfill.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "schema-check":
        schema_check()
    elif args.command == "baseline-stamp":
        baseline_stamp(args.confirm_baseline)
    elif args.command == "db-reset":
        db_reset(args.confirm_reset)
    elif args.command == "generation-worker":
        generation_worker(args.once)
    elif args.command == "project-archive-backfill":
        project_archive_backfill(args.page_size)


if __name__ == "__main__":
    main()
