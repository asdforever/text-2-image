# 参考套图与独立图片任务 Implementation Plan

> **For agentic workers:** Use subagent-driven-development for backend implementation and review; root handles frontend integration. Preserve the existing dirty checkout and do not commit unrelated work.

**Goal:** 用户上传参考套图后自动借鉴顺序与构图，为自己的商品规划独立图片任务，同一模块类型可复用。

**Architecture:** 维持一次规划调用。输入产品图与有序参考图并显式标记角色；输出 taskId 与 moduleId 分离。既有数据库 module_key 保存任务键，真实模块类型保存在快照中；旧请求省略 taskId 时继续用 moduleId。前端 selectedModuleIds 与参数字典继续作为任务键容器，新增 moduleTypes 映射真实目录类型。

**Tech Stack:** FastAPI/Pydantic、PostgreSQL、React/TypeScript、Pytest、tsx、Playwright。

**Spec:** 本任务对话已批准方案，以及 docs/research/2026-09-22-planning-skills-github.md 中已确认的参考套图与重复模块需求。

## Global Constraints

- 不增加 Skill 用户配置；自动选择后端 hero/suite Skill。
- 产品实拍与参考套图分角色，不继承参考中的商品事实、品牌或卖点；参考只指导规划、构图，风格仍归共享规划器。
- 默认根据商品资料增删重排参考结构；不是强制一一复刻。
- `referenceAssetIds` 为有序 UUID 数组，最多 12 张，可为空；与产品素材不重叠，校验工作区、项目、可用状态。
- `taskId` 为可选非空字符串，最多 100 字符；省略时按 moduleId 兼容旧请求。任务键唯一，moduleId 可重复；hero 保持最多 8 个任务，suite 不受模块目录数量限制。
- 用户后续简化：每项一张图，规划结果和前端新编译的 resultCount 固定为 1，移除复制与候选张数控件；旧批次保留原始张数。不同内容必须不同 taskId。
- 不自动调用生图，不调用真实计费模型；恢复页面只读，幂等与人工编辑保留。
- 不重新开 worktree：现有未提交依赖是正在运行应用的一部分；不重启 worker。

## Task 1: Backend contracts and execution

Files: backend/app/application/module_planning_service.py, batch_generation_service.py, suite_planning_service.py, schemas.py, routes/batch_generations.py, routes/suite_plans.py and affected repositories/routes as necessary; tests under backend/tests.

Interfaces:

```python
# Planning input
referenceAssetIds: list[UUID] = Field(default_factory=list, max_length=12)
# Planning output and compile input modules
taskId: str | None = Field(default=None, min_length=1, max_length=100)
# Application compile dataclasses: append task_id: str | None = None
# Persisted key and compilation maps
task_key = selected.task_id or selected.module_id
```

- [x] RED: two entries of one real module with distinct taskId compile to two independent prompts, keys and slots, both hero/suite; duplicate taskId fails, legacy no taskId remains valid.
- [x] RED: reference image order/role reaches provider input and pre-call snapshot; invalid/cross-project/overlapping references fail before model call.
- [x] Implement task-key routing through creation, compilation, confirmation, generation metadata and recovery. Module lookup/constraints always use real moduleId. No schema migration needed if existing unique module_key now stores task key.
- [x] Freeze actual module identity and taskId into snapshots; response views expose moduleId/taskId for UI where appropriate. Keep old rows readable.
- [ ] Reference context: ordered image manifest `imageRoles` with imageIndex (1-based), assetId, role `product` or `reference`, order; image_inputs first product then reference. snapshot referenceAssets separately. References must not be passed as product images downstream.
- [ ] Run focused backend tests and report commands/results; no real models.

## Task 2: Frontend task state and reference UI

Files: src/lib/planning-master.ts, generation-workspace.ts, generation-config.ts, src/hooks/useModulePlanning.ts, src/api/client.ts, HeroConfigPanel.tsx, SuiteConfigPanel.tsx, HeroImageWorkspace.tsx, SuiteWorkspace.tsx, new ReferenceAssetPicker/GenerationTaskSelector components, tests.

Interfaces:

```ts
// CommonGenerationConfig
referenceAssetIds?: string[];
moduleTypes?: Record<string, string>; // task key -> published catalog module id
// Planning item
taskId?: string;
// compile module
{ taskId: taskKey, moduleId: config.moduleTypes?.[taskKey] ?? taskKey,
  resultCount: config.moduleCounts[taskKey], moduleParameters: config.moduleParameters[taskKey] }
```

- [ ] RED: repeated module tasks keep different parameters/counts, reference ordering affects fingerprint, old plan recovery remains compatible.
- [ ] Apply planned tasks keyed by taskId; preserve edits only for corresponding task identity/type. New task IDs must not inherit another task's edits.
- [x] Dedicated ordered reference picker: multiple upload/select/remove/reorder, max12, product/reference exclusion; snapshots/drafts persist IDs.
- [x] Explicit or compile-triggered planning works with reference images and no brief. No automatic model calls on upload, navigation or refresh.
- [x] Render task list, allow adding another task of same module, independent parameters/count/remove/order. Validate catalog identity via moduleTypes, not task key.
- [x] Compile both modes with taskId and real moduleId; confirmation/progress use task labels rather than raw keys where available.
- [x] Mock E2E covers reference upload/selection/order, duplicate tasks/edit/compile, refresh without POST and legacy manual flow.

## Task 3: Skills, integration and review

- [x] Update backend Skill workflow: reference analysis -> product adaptation -> per-task brief. Brief expresses purchase question, grounded main information, layout/subject/text hierarchy and evidence boundary.
- [x] Replace unique-module restriction with unique-task rule. Keep candidate-count meaning. Reference analysis and planning stay one LLM call; no fictional tool access.
- [x] Add small conditional composition examples directly into short Skill files; defer external reference library until runtime loading is needed.
- [x] Validate Skill format; bounded behavioral review with approved inputs; test invalid structures in production validator.
- [ ] Run focused backend/frontend/E2E/build, independent review and fix findings; document limits and results.
- [ ] Restart API after ensuring no active planning, verify health; frontend HMR, worker unchanged.

## Progress

- Design approved in conversation; implementation complete and verified.
- Interface scan: Task1 produces taskId/referenceAssetIds; Task2 consumes exactly these fields. Task3 documents same runtime contract. No shared implementation file between backend worker and root frontend/Skills work.
- Decision: reference style not automatically adopted; user's existing style configuration remains authoritative. A later separate style-reference option can be designed if requested.
- Verification: backend reference/planning tests 36 passed; frontend focused tests 43 passed; module-planning mock E2E 9 passed; production build and local `/api/ready` checks passed. No worker was started or changed.
