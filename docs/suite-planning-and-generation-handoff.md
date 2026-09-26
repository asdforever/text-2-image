# 详情页规划与套图生成交接说明

更新时间：2026-09-15

这份文档用于把 `suite-planning-and-generation` 变更交接给下一位模型（Claude）。后续实现以 OpenSpec 变更文档和本文件为入口，不要依赖聊天记录。

## 当前工作范围

- 当前在主分支直接开发，未使用 worktree。
- 架构按单用户运行，但新接口继续保留 `workspace_id`、`actor_id` 边界。
- 不调用真实计费图片 Provider；自动化测试使用受控假响应。
- 当前不实现阶段 5 的画布布局、节点协作和版本协作。
- 不接回旧 Node 生成接口；项目、素材、配置、主图和套图规划路径走 FastAPI。

## 已完成能力

### 后端

- 详情页规划模型、模块修订、状态机、不可变快照和 Alembic 迁移。
- 规划编译、全部源图快照、参考资料解析边界、只读约束卡和模块提示词绑定。
- 模块独立编辑、数量 1–4 校验、双层乐观修订、模块排序和确认幂等。
- 规划确认后原子创建 `suite` 批次与精确槽位；重复确认不会重复入队。
- Worker 支持多源图、模块间串行、模块内并行、租约恢复、取消和单槽位重试。
- 批次 API 返回来源类型、规划关联、模块位置、总进度、模块进度、槽位状态和安全错误。
- 应用工厂已接入规划仓储、编译器、参考解析器、确认服务和 readiness 检查。

### 前端

- `suitePlanningApi` 已覆盖编译、读取最新/指定规划、模块编辑、排序和确认。
- `SuiteWorkspace` 已移除真实路径的本地 `generatePlan` / `mockGenerateSuite`，改用服务端规划和批次。
- 页面初始化恢复最新规划；确认后轮询关联批次，展示模块/槽位进度、预览、失败、取消、重试和按规划顺序导出。
- 模块可编辑标题、文案摘要、画面说明、实时任务提示词、生成张数和补充参数；约束卡、可见事实和无法确认项只读。
- 主图/详情套图的具体市场、风格、模型、分辨率和每模块张数均来自已发布配置。
- 右侧历史面板的“重新生成此卡”不再调用浏览器模拟，改为提示回到详情套图工作台确认规划。

## 最近验证结果

以下结果是本次交接前已实际运行的证据：

- `python -m pytest -q backend/tests`：234 passed, 5 skipped。
- `npm test`：133 passed。
- `npm run typecheck`：通过。
- `npm run build`：通过；仅有既存的大 chunk 和动态导入提示。
- `npx playwright test tests/e2e/hero-suite-workspace.spec.ts`：5 passed，覆盖主图配置、套图规划/编辑/排序/确认/结果、刷新恢复、失败槽位重试和窄屏布局。
- `python -m backend.cli migrate`：已将远程数据库从 `c9d0e1f2a3b4` 升级到 `d0e1f2a3b4c5`。
- `python -m backend.cli generation-worker --once`：输出 `{\"completed\": 0}`，空队列未调用图片 Provider。
- `alembic upgrade head --sql`：通过。
- `alembic downgrade d0e1f2a3b4c5:c9d0e1f2a3b4 --sql`：通过。
- `openspec validate suite-planning-and-generation --strict`：收尾时重新通过。

## OpenSpec 任务状态

`openspec/changes/suite-planning-and-generation/tasks.md` 中 5.2–6.3 已根据实现和验证证据勾选完成。全量 `npm run test:e2e` 仍有 7 个旧素材库夹具失败，详见阶段 4 交付文档；套图 Playwright 流程本身 5/5 通过。

注意：只有在行为和证据都齐全后才能把任务项改为 `[x]`。不要因为测试数量变化或模型报告成功而直接勾选。

## 已知问题与注意事项

1. Playwright 测试需要 Vite 代理；未启动 FastAPI 时会看到素材预览的 `ECONNREFUSED` 日志，但套图用例已经对规划和批次接口做了 route mock，不会调用真实 Provider。
2. 当前远程数据库已迁移到最新 head；如果本地环境使用另一个数据库，先执行 `python -m backend.cli migrate`，不要手工改表。
3. 旧版 `Project` 类型仍保留本地 `suiteTasks` 等兼容状态，不能把它们当作套图真实执行事实来源。
4. `SuiteWorkspace` 的服务端模块编辑通过 `onBlur` 提交；处理并发冲突时应保留服务端刷新逻辑，不要退回静默覆盖。
5. `references` 当前只提交可被服务端按标识和版本解析的引用；旧草稿中的 `selectedChunkIds` 没有版本信息，不能冒充已冻结引用。

## 建议 Claude 的执行顺序

1. 先读取本文件、`openspec/.../proposal.md`、`specs/**/*.md`、`design.md` 和 `tasks.md`。
2. 检查 `git diff`，确认不要覆盖用户已有的非本变更修改。
3. 重新运行 `npm test`、`python -m pytest -q backend/tests` 和 `npm run typecheck`，确认基线。
4. 重点检查 `SuiteWorkspace.tsx` 的真实接口调用、刷新恢复、模块修订冲突和结果映射；如发现问题，先补测试再修实现。
5. 阶段 4 自动化验证已完成；后续只需在 Provider、对象存储和运行环境就绪后进行统一人工验收。
6. 保持 `docs/backend-architecture-roadmap.md`、本交付文档和任务清单同步；不要接真实计费 Provider 作为自动化验证步骤。

## 交接完成标准

当前阶段 4 自动化实现已经完成；向用户说明时必须同时保留以下边界：

- OpenSpec 5.2–6.3 的实现和证据均已完成。
- 后端全量测试、前端单元测试、类型检查、构建、迁移校验和套图 Playwright 流程通过；全量 E2E 仍有旧素材库夹具失败，不能表述为全量 E2E 全部通过。
- 文档和任务清单为中文且 UTF-8 检查通过。
- 明确说明真实图片 Provider 尚未在自动化阶段调用，下一步由用户统一人工验收。
