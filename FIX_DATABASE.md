# 数据库修复与迁移排查

## 命令入口

Alembic 是唯一有效的数据库迁移来源，应用启动不会执行 DDL。旧表 `schema_migrations` 仅保留作历史审计，不再驱动任何迁移。

| 目的 | 正确命令 |
| --- | --- |
| 升级到最新结构 | `python -m backend.cli migrate` |
| 只读检查结构兼容性 | `python -m backend.cli schema-check` |
| 已有库一次性基线登记 | `python -m backend.cli baseline-stamp --confirm-baseline` |
| 开发库重置（仅 development） | `python -m backend.cli db-reset --confirm-reset` |
| 查看当前版本 | `alembic current` |
| 查看版本头 | `alembic heads` |
| 离线推演 SQL（不连库） | `alembic upgrade head --sql` |

**不要使用 `python -m alembic ...`。** 仓库根目录的 `alembic/` 迁移脚本目录会遮蔽同名的 Python 包，命令必然报：

```
No module named alembic.__main__; 'alembic' is a package and cannot be directly executed
```

请直接使用 `alembic` 控制台命令，或统一走 `python -m backend.cli`。

## 历史问题：`record "old" has no field "stage"`

创建提示词时报此错误，原因是 `prompt_library.protect_prompt_version()` 触发器引用了已被删除的 `stage` 字段。

该问题已由迁移 `667ae46e4354_fix_prompt_versions_trigger` 和 `3af2e3c6054f_fix_protect_prompt_version_trigger_` 修复。执行升级后重启后端：

```powershell
python -m backend.cli migrate
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

如果升级后仍然报错，手工检查并删除残留触发器：

```sql
-- 查看触发器
SELECT tgname, pg_get_triggerdef(oid)
FROM pg_trigger
WHERE tgrelid = 'prompt_library.prompt_versions'::regclass
AND tgisinternal = false;

-- 按上一步查到的名称删除
DROP TRIGGER IF EXISTS <trigger_name> ON prompt_library.prompt_versions;
```

## 版本指针与实际结构不一致

如果 `alembic current` 显示的版本远落后于 `alembic heads`，但库里其实已经有全部表，说明版本指针失真（典型场景：数据库由旧迁移系统建立后被错误地 stamp 到起始版本）。

此时 `migrate` 会尝试重放历史迁移，并在第一条裸 `CREATE TABLE` 处因对象已存在而失败，整个事务回滚。**不要反复重试 `migrate`**，按下面的步骤处理：

1. **先备份数据库。**
2. 只读检查当前结构是否已与 Alembic head 一致：
   ```powershell
   python -m backend.cli schema-check
   ```
3. 只有输出 `{"compatible": true, ...}` 时，才执行基线登记：
   ```powershell
   python -m backend.cli baseline-stamp --confirm-baseline
   ```
   该命令只登记 Alembic head，不重放历史 DDL，也不删除旧 `schema_migrations` 记录。
4. 用 `alembic current` 复核，应显示当前 head。

若 `schema-check` 列出缺失结构，**必须停止**，先在数据库副本上制定专项迁移方案，不能强行 stamp。

## 开发库重置

`db-reset` 会删除全部应用 schema（`project_workbench`、`generation_config`、`suite_workbench`、`prompt_library`）和 `public.alembic_version`，然后重新执行全部迁移。它只在 `ENVIRONMENT=development` 且显式传入 `--confirm-reset` 时执行。

```powershell
python -m backend.cli db-reset --confirm-reset
```
