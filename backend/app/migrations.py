"""旧迁移系统的只读审计标识。

新建、升级和回滚数据库只能通过仓库根目录的 Alembic 迁移图执行。
本模块不得重新加入 DDL 执行器。
"""

LEGACY_MIGRATION_TABLE = "schema_migrations"
