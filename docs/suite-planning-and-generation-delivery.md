# 阶段 4：详情页规划与套图生成交付记录

更新时间：2026-09-15

对应 OpenSpec：`suite-planning-and-generation`

## 交付范围

阶段 4 将详情页套图从浏览器本地模拟状态接入服务端规划与批次执行链路：

1. 使用项目已选源图、已发布市场/平台、风格、模型、分辨率和模块目录编译详情页规划。
2. 在确认前展示约束卡、可见事实和无法确认项；模块文案、画面说明、实时任务提示词、补充参数和生成张数可独立编辑。
3. 规划确认时冻结规划修订、源图/引用/配置快照，并原子创建 `suite` 批次和全部槽位。
4. Worker 按模块位置串行推进，模块内槽位并行；支持进度查询、刷新恢复、取消和失败槽位单独重试。
5. 结果按规划顺序展示和导出，重试不会覆盖其他已成功结果。

当前仍是单用户实现，但接口保留 `workspace_id`、`actor_id` 边界；本阶段不实现阶段 5 画布，也不接回旧 Node 生成接口。

## 自动化验证证据

以下命令在本次收尾中实际运行：

| 验证项 | 结果 |
| --- | --- |
| `python -m pytest -q backend/tests` | 234 passed，5 skipped |
| `npm test` | 133 passed |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过；仅有既存的大 chunk 与动态导入提示 |
| `npx playwright test tests/e2e/hero-suite-workspace.spec.ts` | 5 passed；覆盖规划、模块编辑/排序、确认、结果、刷新恢复、失败槽位重试和响应式布局 |
| `python -m backend.cli migrate` | 远程数据库从 `c9d0e1f2a3b4` 升级到 `d0e1f2a3b4c5` |
| `python -m backend.cli generation-worker --once` | 输出 `completed: 0`；空队列且未调用图片 Provider |
| `alembic upgrade head --sql` | 通过 |
| `alembic downgrade d0e1f2a3b4c5:c9d0e1f2a3b4 --sql` | 通过 |
| `node scripts/check-utf8-docs.mjs` | 通过 |
| `openspec validate suite-planning-and-generation --strict` | 通过 |
| `git diff --check` | 通过；无空白错误 |

`npm run test:e2e` 的全量结果为 9 passed、7 failed。7 个失败全部来自旧的 `base-image-library-picker.spec.ts`，该测试依赖未启动 FastAPI 时的旧项目接口夹具；本阶段套图流程的 5 个 Playwright 用例均已通过，失败不涉及 `SuiteWorkspace` 的规划和批次链路。素材预览在未启动 FastAPI 时会出现 Vite 代理 `ECONNREFUSED` 日志，但套图用例对规划和批次接口使用受控夹具，不会调用真实 Provider。

## Provider 与数据安全边界

- 自动化测试只使用受控假响应，不调用真实计费图片 Provider。
- 多源图请求只将源图哈希和必要的请求摘要写入记录，不把原图内容写入 Provider 请求摘要。
- 真实生图仍需在用户统一人工验收阶段，在已配置 Provider、对象存储和运行环境后执行。

## 当前阶段结论

阶段 4 的代码、接口、批次执行、恢复/重试路径和自动化证据已经完成，OpenSpec 任务 5.2–6.3 已勾选。当前结论是“自动化验证完成，待最终统一人工验收”，不是“真实生图已验收”。

