# 规划大师自动模块规划 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让主图和详情图在用户提交商品资料后由规划大师自动选择模块、排序并生成模块级构图简案，再由模块规划器细化；详情模块数量不再被 5 个限制。

**Architecture:** 主图和套图共享独立的持久化前置规划接口。规划大师选择模块、分配参数并输出构图简案；随后沿用既有风格规划和各模块编译流程，最终仍需用户确认才生成图片。无资料时保留手动模块流程；有资料且规划已过期时，在编译前自动规划。恢复页面只读状态，不发起模型调用。

**Tech Stack:** FastAPI/Pydantic、Python application services、PostgreSQL/Alembic、React/TypeScript、tsx node:test、Playwright、Pytest。

**Spec:** `openspec/changes/suite-planning-and-generation/design.md` plus the approved planning-master discussion in the linked Codex task.

## Global Constraints

- 规划大师只能选择已发布配置中的模块 ID，不能发明模块。
- 构图简案是规划大师输出、模块编译器输入，不是用户必填字段。
- 风格规划仍只负责全局视觉语言，模块编译器不得重写全局风格。
- 不调用真实计费 Provider；测试使用受控假规划大师/编译器。
- 保留现有未提交改动，不 reset、checkout 或清理无关文件。

## 执行时核对与调整

- 共享前置接口采用 `POST /api/projects/{projectId}/module-plans`，同时服务 hero/suite；不把自动规划仅嵌入 suite 编译器，避免遗漏主图。
- 新增 `module_plans` 持久记录和 latest 查询，保存原文、配置/提示词版本、状态、结果；编译接口接受 `modulePlanId` 冻结来源。已有手动编译请求保持兼容。
- 规划大师独立输出 `compositionBrief`，同时以“建议构图简案”补充参数自动回填模块；用户编辑后，以编译请求中参数为执行依据，原规划作为可追溯来源。
- 主图/套图各使用后端内置的独立 Skill，由开发者维护。移除 `plannerBindings` 和用户配置入口，继续使用现有提示词模型连接。
- 新界面显式点击自动规划，或编译时自动完成规划；不在进入页面或失焦时隐式付费调用。
- 在当前 `codex/shared-style-planning` 分支接着既有未提交依赖开发，保持本地运行工作区一致，不另建丢失依赖的 checkout，不提交无关修改。
- 分工：前端子任务负责 src/tests；主任务负责 backend/alembic、集成与验证。回归覆盖自动选模块、输入改动后的陈旧响应、持久恢复、错误与幂等。

## 已落地接口与边界（取代下方原始任务草案中的接口命名）

- `POST /api/projects/{projectId}/module-plans`：`mode`、`sourceAssetIds`、`marketId`、`aspectRatio`、`outputLanguage`、`brief`；要求 `Idempotency-Key`。
- `GET /api/projects/{projectId}/module-plans/latest?mode=hero|suite` 和 `GET /api/projects/{projectId}/module-plans/{id}`：只读取既有规划；状态为 `planning/completed/failed`。
- 输出 `summary/modules/warnings`；模块输出 `moduleId/resultCount/moduleParameters/compositionBrief/reason`。仅允许已发布模块，每个模块最多一次，每模块 1–4 张。
- 服务端规范化唯一的 `建议构图简案` 参数。编译使用用户最终确认的模块参数；原规划冻结在 `planningMaster` 中，保留来源。
- 调用模型之前持久化原文、配置版本、Skill 正文及哈希、模型连接快照与素材哈希。失败、中断和过期记录均可恢复，幂等重试不会重复调用。
- 按模式固定加载 `backend/app/skills/hero-planning-master/SKILL.md` 或 `backend/app/skills/suite-planning-master/SKILL.md`。用户不选择、不绑定、不编辑 Skill；旧配置的规划大师绑定不再执行，历史任务快照保留。Skill 文件缺失时明确报错，不回退到商城提示词。
- 原文中的风格诉求传入共享风格规划器；模块编译器只获得自己分配到的参数和构图简案。
- 迁移 `b9c0d1e2f3a4` 已在本机执行；移除套图数量/位置的 5 个上限。模块重排使用动态偏移，避免数量超过旧偏移量时冲突。

交付验证：后端 59 项聚焦测试通过；真实 PostgreSQL 事务回滚测试 2 项通过（6 与 101 模块创建/重排、规划恢复、幂等与终态保护）。前端聚焦单测 18 项、新增浏览器 mock 流程 8 项通过，类型检查与构建通过。所有测试使用假 Provider，不产生模型费用。全量套件仍有既有断言失败（后端 2 项、前端 4 项），具体差异与使用说明见 `docs/planning-master-handoff.md`。

下方保留最初讨论任务，仅用于记录设计演变；交付以本节和“执行时核对与调整”为准。

---

### Task 1: 定义规划大师结构化协议并补失败测试

**Files:**
- Modify: `backend/app/application/suite_planning_service.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_suite_planning_service.py`
- Test: `backend/tests/test_suite_planning_api.py`

**Interfaces:**
- `SuitePlanCompilationInput` 接受可选 `auto_plan: bool = True` 与 `planning_brief: str = ""`。
- 新增 `SuitePlanningMasterResult` 规范字段：`summary`、`modulePlans`、`unassignedFacts`、`warnings`。每个 `modulePlan` 包含 `moduleId`、`order`、`imageCount`、`reason`、`compositionBrief`。
- 规划大师异常或非法模块 ID 必须返回 `SUITE_PLAN_PLANNER_INVALID`/`SUITE_PLAN_PLANNER_FAILED`，不创建待确认规划。

- [ ] **Step 1: Write the failing tests**
  - 用假规划大师返回两个已知模块和一个 `compositionBrief`，断言编译请求只收到规划大师选中的模块，模块快照包含 `planningMaster.compositionBrief`。
  - 用假规划大师返回未知模块 ID，断言服务返回 502/`SUITE_PLAN_PLANNER_INVALID`。
  - 用 6 个模块请求断言服务层不再因数量上限拒绝。

- [ ] **Step 2: Run tests to verify they fail**
  - `python -m pytest -q backend/tests/test_suite_planning_service.py backend/tests/test_suite_planning_api.py`
  - Expected: planner master is not invoked/fields are absent and the 6-module request is rejected.

- [ ] **Step 3: Implement the minimal protocol and adapter**
  - 添加严格的结果归一化函数；对 module ID、顺序连续性、图片张数和构图简案长度做服务端校验。
  - 自动规划时把结果转换为现有 `SuitePlanModuleInput`，将 `compositionBrief` 写入模块 `prompt_snapshot.planningMaster`，并把它注入 `_compiler_prompts` 的结构化输入。
  - `autoPlan=false` 时保留旧模块列表路径。

- [ ] **Step 4: Run focused tests**
  - `python -m pytest -q backend/tests/test_suite_planning_service.py backend/tests/test_suite_planning_api.py`
  - Expected: all focused tests pass.

### Task 2: 移除详情规划的 5 模块限制

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/application/suite_planning_service.py`
- Modify: `backend/app/suite_planning_repository.py`
- Modify: `backend/app/models/suite_planning.py`
- Create: `alembic/versions/<new_revision>_expand_suite_plan_module_count.py`
- Modify: `src/components/SuiteConfigPanel.tsx`
- Modify: `src/pages/SuiteWorkspace.tsx`
- Modify: `src/lib/generation-workspace.ts`
- Test: `tests/suite-planning-api-client.test.ts`
- Test: `tests/suite-planning-workspace.test.ts`

**Interfaces:**
- API `modules`, `moduleIds`, `moduleTaskPrompts` accept the complete published suite module catalog (current catalog size, not an arbitrary client-supplied ID).
- Database constraints permit positive positions and counts; no hard-coded 5.

- [ ] **Step 1: Write failing boundary tests**
- [ ] **Step 2: Run focused frontend/backend tests and observe the 5-module failure**
- [ ] **Step 3: Remove max-length/position checks and add migration dropping old checks**
- [ ] **Step 4: Update UI count labels and automatic selection state**
- [ ] **Step 5: Run focused tests and typecheck**

### Task 3: Verify snapshot recovery and prompt boundaries

**Files:**
- Modify: `backend/tests/test_suite_planning_service.py`
- Modify: `tests/e2e/hero-suite-workspace.spec.ts`
- Modify: `docs/suite-planning-and-generation-handoff.md`

- [ ] **Step 1:** Assert refresh/reload returns `planningMaster` and per-module briefs.
- [ ] **Step 2:** Assert module compiler receives only its own brief plus the frozen style snapshot.
- [ ] **Step 3:** Run `python -m pytest -q backend/tests`, `npm test`, `npm run typecheck`, and `git diff --check`.
