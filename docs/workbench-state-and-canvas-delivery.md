# 阶段 5：工作台状态与画布交付

## 已实现能力

- 工作台任务、任务版本、画布布局和资源引用使用 PostgreSQL/内存仓储，带工作区和项目边界。
- 任务支持从已确认详情页规划幂等创建、提示词与生成参数编辑、任务修订冲突保护和归档。
- 单卡与批量生成触发只解析已有确认批次，不直接调用图片 Provider。
- 任务版本支持当前版本/终版互斥选择；画布节点、分组、视口支持版本化保存和冲突拒绝。
- 工作台聚合返回规划快照、任务版本、批次摘要、源图投影、布局和活动引用。
- 前端工作台客户端携带 `expectedRevision`，支持刷新恢复、参数编辑、版本选择和布局防抖保存。
- 详情页工作区提供“打开工作台画布”入口，画布地址为 `/suites/{项目ID}/board`。

## 自动化验证

- 后端：`252 passed, 6 skipped`（`python -m pytest backend/tests -q`）。
- 前端：`134 passed`（`npm test`）。
- 类型检查：`npm run typecheck -- --pretty false` 通过。
- 生产构建：`npm run build` 通过；仅保留 Vite 大 chunk 提示。
- UTF-8 文档检查：108 个 Markdown 文件通过。
- Alembic 工作台迁移已完成离线升级/回滚 SQL 检查；连接真实业务库时执行 `python -m backend.cli migrate`。
- PostgreSQL 仓储契约：`6 passed, 1 skipped`；跳过项因未设置包含 `test` 的专用 `PICAGENT_MIGRATION_TEST_DATABASE_URL`，不会连接业务数据库。
- Playwright 工作台流程：`npx playwright test tests/e2e/workbench-board.spec.ts` 通过，覆盖编辑提示词、拖动节点、布局刷新恢复、版本设为当前，并断言未调用真实 Provider。

## 人工验收边界

请在已配置数据库和对象存储的环境中统一验收：进入项目详情页，生成并确认规划，打开工作台画布，编辑提示词/参数、拖动节点、刷新页面并选择当前/终版。当前阶段不包含多人实时协作、评论、权限锁、实时同步和真实 Provider 计费调用。
