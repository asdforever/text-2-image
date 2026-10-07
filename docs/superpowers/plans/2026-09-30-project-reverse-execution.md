# 项目反推执行方案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为项目增加独立的“项目反推”工作区，把已发布反推版本转换成可编辑、可保存、按参考图一一对应的执行任务。

**Architecture:** 后端在反推域旁新增执行方案仓储和服务，使用 JSON 文档保存任务数组，支持内存和 PostgreSQL。前端在现有项目工作台增加 `reverse` 标签，调用执行方案接口展示、编辑、编译和逐张生成任务；每张生成只携带商品资产和模块拆解提示词，并自动归档项目成品库。参考图仅用于分析、页面对照和来源追踪。

**Tech Stack:** FastAPI, Pydantic, PostgreSQL/Alembic, React, TanStack Router, Vitest/tsx, pytest。

**Spec:** `docs/superpowers/specs/2026-09-30-project-reverse-execution-design.md`

## Global Constraints

- 保留现有爆品图反推分析数据和页面。
- 参考图数量、顺序和执行任务数量必须一一对应。
- 项目反推任务保留参考图 ID 以追踪来源，生成模型只接收商品图和拆解提示词，结果自动归档到项目成品库。
- 不修改主图、详情套图、白底图和画布已有接口语义。

### Task 1: 执行方案领域对象和生成规则

**Files:**
- Create: `backend/app/application/reverse_execution.py`
- Test: `backend/tests/test_reverse_execution.py`

- [ ] 写测试：参考图按 ordinal 生成同数量任务；模块按 referenceImageId 匹配；缺少模块时使用安全的空结构。
- [ ] 运行 pytest 确认测试因模块不存在而失败。
- [ ] 实现 Pydantic 模型、`build_execution_plan(document, version_id)` 和 `compile_task_prompt(item, product_facts)`。
- [ ] 运行测试确认通过。

### Task 2: 执行方案仓储和数据库迁移

**Files:**
- Create: `backend/app/reverse_execution_repository.py`
- Create: `alembic/versions/20260930_add_reverse_execution_plans.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_reverse_execution_repository.py`

- [ ] 写内存仓储测试：创建、读取、按 expectedRevision 保存。
- [ ] 运行测试确认失败。
- [ ] 实现内存和 PostgreSQL 仓储，新增 `project_workbench.reverse_execution_plans` 表。
- [ ] 注入 `app.state.reverse_execution_service`。
- [ ] 运行仓储测试和迁移结构测试。

### Task 3: 后端 API

**Files:**
- Create: `backend/app/routes/reverse_execution.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_reverse_execution_api.py`

- [ ] 写 API 测试：生成、读取、保存编辑、编译提示词。
- [ ] 运行测试确认失败。
- [ ] 实现 `GET/POST /api/projects/{project_id}/reverse-execution`、`PATCH /api/projects/{project_id}/reverse-execution` 和 `POST /api/projects/{project_id}/reverse-execution/compile`。
- [ ] 运行 API 测试确认通过。

### Task 4: 前端 API 和项目反推工作区

**Files:**
- Modify: `../text-2-image-front/src/api/reverse-projects.ts`
- Create: `../text-2-image-front/src/api/reverse-execution.ts`
- Create: `../text-2-image-front/src/pages/ProjectReverseWorkspace.tsx`
- Modify: `../text-2-image-front/src/pages/ProjectWorkbench.tsx`
- Modify: `../text-2-image-front/src/routes/router.tsx`
- Modify: `../text-2-image-front/src/index.css`
- Test: `../text-2-image-front/tests/project-reverse-workspace.test.tsx`

- [ ] 写组件测试：显示项目反推标签、任务数量与模板图；保存编辑后显示已保存状态。
- [ ] 运行测试确认失败。
- [ ] 实现页面和 API 调用，按任务顺序展示模板图、模块标签、结构字段和提示词草稿。
- [ ] 运行前端组件测试和 typecheck。

### Task 5: 项目反推图片生成与归档

**Files:**
- Create: `backend/app/application/reverse_execution_generation_service.py`
- Modify: `backend/app/routes/reverse_execution.py`
- Modify: `backend/app/main.py`
- Modify: `../text-2-image-front/src/api/reverse-execution.ts`
- Modify: `../text-2-image-front/src/pages/ProjectReverseWorkspace.tsx`
- Test: `backend/tests/test_reverse_execution_generation_service.py`

- [x] 每个任务携带项目商品图和对应的拆解提示词调用图片编辑模型，参考图文件不参与生成请求。
- [x] 生成资产写回任务并归档到项目成品库。
- [x] 支持整套逐张生成和单张重试，失败任务保留失败状态。

### Task 6: 回归验证

- [ ] 运行后端反推、规划和项目资产相关测试。
- [ ] 运行前端反推规划、工作台交互和项目反推测试。
- [ ] 运行前端 build。
- [ ] 检查 git diff，确认没有修改既有反推分析语义。

### Task 7: 参数逐图分配与输出设置

- [ ] 后端测试先验证参数按稳定任务 ID 分配，缺项/重复项不能写入，单图提示词不含其他图参数。
- [ ] 新增参数分配模块，复用已发布提示词模型连接、商品图读取及模块规划请求端口；新增自动填写 API 并保存修订号。
- [ ] 接通语言、模型、宽高比和分辨率的持久化及出图连接，验证图片请求和归档快照。
- [ ] 前端合并资料输入框，复用 ModuleParameterEditor 和 OutputSettings；自动填写、编辑、刷新及编译/出图流程验证。
- [ ] 检查桌面/移动端截图、构建和相关回归，重启后端后交给用户验证模型实际效果。
