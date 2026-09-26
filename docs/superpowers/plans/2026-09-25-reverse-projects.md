# Reverse Projects Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the bounded backend task; parent owns frontend and integration. Preserve the existing dirty checkout.

**Goal:** 将已批准的项目型爆品反推设计接入真实数据和主图/套图规划链路。
**Architecture:** 独立持久化反推项目和不可变版本，业务项目按工作台及模块保存版本绑定；既有规划服务注入固定版本的设计参考。
**Tech Stack:** React, TypeScript, FastAPI, Postgres, MinIO, pytest, Playwright.
**Spec:** docs/superpowers/specs/2026-09-25-reverse-projects-design.md

## Global Constraints
- 工作目录保持当前用户正在运行的项目；不 reset、stash、删除或提交他人的修改。
- 确切契约以 Spec 为准；只使用真实 API 和真实状态，不写演示数据。
- 上传旧图或发布新版本不会改变已经固定的版本。
- 不复制竞品参数、价格、认证、功效。
- 新行为先写失败测试，再实现，再运行验证。

## Task 1: Reverse project backend
Files: backend/app/reverse_project_repository.py, backend/app/application/reverse_project_service.py, backend/app/routes/reverse_projects.py, backend/app/main.py, alembic/versions/<next>_reverse_projects.py, backend/tests/test_reverse_projects.py.
Produces: Spec 中所有反推 CRUD/分析/发布/绑定接口；ReverseProjectService.get_version(version_id) 和 planning_context(version_id, module_id=None)，后者返回 { versionId, reverseProjectId, versionNo, name, introduction, overall, modules }，module_id 指定时 modules 只含一个完整模块，否则只含模块摘要；planning_images(version_id, module_id=None) 返回 (bytes[], mimeTypes[])，整体无需加入图片、局部只返回对应图片。
- [ ] 编写 API 测试，确认 GET /api/reverse-projects 最初 404，创建/发布/绑定行为当前缺失。
- [ ] 实现带工作区限制、锁与版本不可变保证的仓储和数据库迁移。
- [ ] 实现图片上传、真实模型分析、失败保留草稿、发布校验、双向绑定。
- [ ] 注册应用依赖及路由，运行 pytest backend/tests/test_reverse_projects.py。

## Task 2: Frontend project workspace
Files: src/api/reverse-projects.ts, src/features/reverse-projects/*, src/pages/ReverseProjectsPage.tsx, src/pages/ReverseProjectDetailPage.tsx, src/routes/router.tsx, src/components/GlobalSidebar.tsx, tests/reverse-projects-api.test.ts, tests/e2e/reverse-projects.spec.ts.
Consumes: Task 1 的 API 契约，使用独立 TS 类型。
- [ ] 编写 API 请求与版本绑定错误处理测试，运行 tsx --test tests/reverse-projects-api.test.ts 验证失败。
- [ ] 实现独立 client 和类型；列表搜索/创建、四个详情 Tab、图片上传/排序/删除、编辑/分析/发布与版本查看、绑定弹窗。
- [ ] 复用现有导航和 C 版布局，页面内展示加载、错误、空状态；弹窗支持键盘退出和焦点。
- [ ] Playwright 测试实际页面从新建到绑定、刷新读取和失败重试；npm run build。

## Task 3: Planner integration
Files: src/features/reverse-projects/ReverseReferencePanel.tsx, src/components/HeroConfigPanel.tsx, src/components/SuiteConfigPanel.tsx, src/hooks/useModulePlanning.ts, src/lib/generation-workspace.ts, src/lib/planning-master.ts, src/api/client.ts, backend/app/application/module_planning_service.py, backend/app/application/module_planning_v2.py, relevant generation services and tests.
Consumes: ReverseProjectService planning_context / planning_images 及固定版本绑定；与 backend 主任务避免并行编辑 main.py。
- [ ] 编写整体/模块引用注入和指纹变化回归测试，确认目前请求不含引用。
- [ ] 工作台加载当前绑定；主图和套图分别选择反推版本，每个已选模块可选择局部参考。
- [ ] 整体规划只学习整体策略与模块摘要；模块编译读取局部详情和原图，继承整体规则；所有引用进入快照。
- [ ] 运行规划大师、主图、套图相关测试和新 e2e。

## Task 4: Verification and delivery
- [ ] 执行数据库迁移并验证 Postgres 重建仓储后仍能读回版本与绑定；测试数据事务回滚。
- [ ] 执行相关 pytest、TypeScript tests、前端构建和浏览器交互测试。
- [ ] 视觉检查反推列表、详情、绑定和工作台引用；确认没有 mock 生产数据。
- [ ] 报告实际完成能力和未纳入本次的自动匹配/长图分段。
