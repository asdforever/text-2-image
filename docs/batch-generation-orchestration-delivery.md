# 批次生成编排交付说明

## 启动顺序

1. 配置数据库、对象存储、多模态提示词编译模型和图片 Provider。
2. 执行 `python -m backend.cli migrate`，确保 Alembic revision 为 `c9d0e1f2a3b4`。
3. 启动 API 后，另开终端执行 `python -m backend.cli generation-worker`。
4. 部署检查可使用 `python -m backend.cli generation-worker --once`；空队列只会输出完成数量，不会调用图片 Provider。

## 成本确认

- 批次提示词编译仅调用多模态提示词编译模型，不调用图片 Provider。
- 用户确认批次后，系统按模块选择的数量创建图片槽位；每个槽位最多对应一次实际图片 Provider 调用。
- Worker 在 Provider 调用结果不确定时将槽位标记为“需要人工重试”，不会自动发起第二次调用。

## 前端验收

1. 在主图工作台选择两个模块，并分别选择 3 张和 2 张。
2. 点击编译提示词，确认两个模块各有一条可编辑任务提示词、只读约束卡和对应数量。
3. 确认后观察总进度为 5；Worker 启动后每张结果独立更新。
4. 取消未执行槽位后，已成功图片保留；对失败或结果不确定槽位使用单槽位重试。

## 自动化验证记录

2026-09-14 完成以下验证：

- `python -m pytest -q backend/tests`：203 项通过，4 项跳过。
- `npm test`：129 项通过。
- `npm run typecheck`：通过。
- `npm run build`：通过；仅保留现有的前端分块体积提示。
- `npx playwright test tests/e2e/batch-generation.spec.ts`：1 项通过，覆盖确认前不生图、多模块 3+2 槽位、刷新恢复和历史主图保留。
- `openspec validate batch-generation-orchestration --strict`：通过。
- `node scripts/check-utf8-docs.mjs README.md docs openspec`：110 个 Markdown 文件通过。
- `git diff --check`：通过；仅输出 Windows 换行符提示。
