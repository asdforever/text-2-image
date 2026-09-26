# 后端运行时基线交付记录

> 历史验收记录：2026-09-21 已移除旧 Node API 代理和未挂载入口。下文 Node 回切事项不再作为当前部署要求；现行方式见 `backend-selective-cutover.md`。

记录日期：2026-09-15

## 当前结论

OpenSpec 变更 `backend-runtime-baseline` 已完成 17/20 项。本地代码、契约、迁移图、编译和前端回归均通过；真实升级/回滚与 Node 回切仍需外部专用环境，因此阶段 0 尚未标记完成。

## 已完成验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| OpenSpec 严格校验 | `openspec validate backend-runtime-baseline --strict` | 通过 |
| Python 全量测试 | `python -m pytest -q backend/tests` | 234 通过，5 个外部集成项跳过 |
| Python 编译 | `python -m compileall -q backend` | 通过 |
| 前端类型检查 | `npm run typecheck` | 通过 |
| 前端单元/契约测试 | `npm test` | 133 通过 |
| 前端生产构建 | `npm run build` | 通过；存在既有的大包体积和动态导入提示 |
| Alembic 离线全链路 | Python 测试 `test_offline_upgrade_adds_generation_params_only_once` | 通过，已确认 `generation_params` 只添加一次 |

## 未完成的环境验收

### 4.4 专用 PostgreSQL 升级/回滚

本机 Docker 未运行，也未安装本地 PostgreSQL 工具。当前项目 `.env` 指向远程 `cjs_pg`，不是明确的专用测试库，因此未在该库执行任何降级或清理操作。

已准备受保护测试：`backend/tests/test_postgres_migration_roundtrip.py`。它只接受数据库名包含 `test` 的显式变量：

```powershell
$env:PICAGENT_MIGRATION_TEST_DATABASE_URL="postgresql+asyncpg://.../picagent_migration_test"
python -m pytest backend/tests/test_postgres_migration_roundtrip.py -q
```

该测试会在专用库执行 `base -> head -> b7c2e4d91a6f -> head`，并检查 suite 与 input-image 数据在回滚前后保持存在。

### 5.3 Node 回切冒烟

当前仓库没有旧 Node API 服务实现，无法真实启动 `3001` 并验证停止 FastAPI 后仍能读取同一数据库记录和 MinIO 对象。选择性代理与回滚步骤已记录在 `docs/backend-selective-cutover.md`，待旧 Node 服务可用后执行。

### 5.4 外部集成收口

本地校验已经完成，`openspec validate backend-runtime-baseline --strict`、`python -m compileall -q backend` 和后端全量测试均通过。由于 4.4 和 5.3 仍缺少专用 PostgreSQL 与旧 Node 环境，5.4 暂不勾选；这些外部验收不会阻塞后续业务代码实现，但在统一人工验收前必须补齐。
