# Design-guided Commerce Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将经过适配的设计知识真实接入规划大师，让主图/套图的新任务先确定购买问题和视觉表达，再归类执行，支持新任务编辑、刷新恢复与失败重试。用户已明确旧任务无需兼容。

**Architecture:** 应用离线加载版本化设计知识，大师输出有信息目标和设计指南引用的任务书，单图编译器按任务加载指导并展开可调整构图。统一运行时模块目录提供自由创意执行类型；保留现有 taskId、模块服务和冻结快照机制。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、现有 PostgreSQL JSON 快照；React 19、TypeScript、Zustand、tsx/node:test；不新增运行时依赖。

**Spec:** `docs/superpowers/specs/2026-09-28-design-guided-commerce-planning.md`

## Global Constraints

- 商品事实、平台适用规则、用户明确要求优先于设计建议；创意不得编造参数、内部结构、认证、实测数据、承诺或人群适用结论。
- 不按商品品类写死版式，不规定每套必须有无产品图；商品出场方式应由信息表达决定。
- 主图最多 8 个任务，每个任务生成 1 张；沿用现有套图数量机制，不在此扩大限制。
- 第一版不增加模型调用阶段；知识加载完全离线，不增加运行时第三方依赖。
- 仅支持新任务；不实现旧任务兼容、迁移或清理。当前工作区配置继续服务新任务，不改写不可变发布版本。
- 不覆盖已有未提交改动，不修改数据库连接、并发配置、远端服务或项目素材。

## 路径与执行前提

后端根：`C:/Users/jack/Desktop/item-zuizhong2/text-2-image`（下文 B）。
前端根：`C:/Users/jack/Desktop/item-zuizhong2/text-2-image-front`（下文 F）。

两者是独立 Git 仓库，父目录不是 Git 仓库。所有 B/F 路径分别相对其根目录。执行前记录两仓 `git status --short`，保留已有改动；若创建隔离工作树，必须明确当前依赖的未提交行为如何保留，不能从 HEAD 丢掉已经完成的重试/并发/前端修复。只提交本任务路径或经逐块检查的本任务改动。

文档日期 2026-09-28。本计划未执行；文档不代表已接入 Skill 或已验证成图效果。

## 文件职责

| 文件 | 职责 |
|---|---|
| B `backend/app/data/commerce_design_v1/manifest.json`、`guides.json`、`LICENSES/`、`NOTICE.md` | 知识内容、固定来源、许可和改写记录 |
| B `backend/app/application/commerce_design.py` | 加载、校验、按 ID 选择、hash 与序列化 |
| B `backend/app/application/runtime_module_catalog.py` | 不变配置上的运行时执行目录 |
| B `backend/app/application/module_planning_service.py` | 大师实际请求、响应契约、输入指纹、快照 |
| B `backend/app/skills/hero-planning-master/SKILL.md`、`suite-planning-master/SKILL.md` | 按购买问题规划及内容边界 |
| B `backend/app/application/module_planning_v2.py` | 单图指导、建议与显式要求优先级 |
| B `backend/app/application/generation_config_service.py`、`batch_generation_service.py`、`suite_planning_service.py`、`hero_generation_service.py` | 目录及任务上下文贯通 |
| F `src/api/client.ts`、`src/lib/planning-master.ts`、`src/lib/generation-workspace.ts` | 新契约请求/响应、指纹、编辑状态和恢复 |
| F `src/store/useGenerationConfigStore.ts`、`src/lib/generation-config.ts` | 运行时目录消费，保留配置管理原语义 |
| F `src/components/generation-workspace/GenerationTaskSelector.tsx`、`src/components/image-canvas/LongImagePlanningAdvice.tsx` | 任务标题、目的、商品出场和构图建议 |
| F `src/pages/HeroImageWorkspace.tsx`、`src/pages/SuiteWorkspace.tsx` | 规划恢复、提交、错误展示和两种模式接通 |

## Task 1：离线设计知识包与选择器

**Files:** 创建上述 commerce_design_v1 资源、B `backend/app/application/commerce_design.py`、B `backend/tests/test_commerce_design.py`。

**Interfaces:**

```python
def load_commerce_design() -> dict: ...
def commerce_design_context(guide_ids: list[str] | None = None) -> dict: ...
# None: 大师的完整精简包；list: commerce-core + 所选辅助指南。
# 返回 version, contentSha256, sources, guides；每个 guide 含 id, rules。
# 每次返回独立值，调用者修改不能污染缓存。
```

- [ ] 加入加载及选择行为测试；未知 ID 抛 `AppError("DESIGN_GUIDE_INVALID", ..., 422)`，缺文件/坏资源报 `COMMERCE_DESIGN_UNAVAILABLE` 503，禁止静默降级为“已启用”。
- [ ] 运行 `python -m pytest backend/tests/test_commerce_design.py -q`，确认因新模块缺失失败。
- [ ] 实现加载器及规则包。来源固定为研究文档中的 commit，写入适配内容和对应 LICENSE/NOTICE。四项规则正文合计不超过 6,000 字符；不要复制整套外部 SKILL.md。
- [ ] 运行同一测试，验证选择、稳定 hash、重复 ID、不可变性和错误路径。
- [ ] 检查并提交本任务文件：`git commit -m "feat: add versioned commerce design guidance"`。

关键测试示例：

```python
def test_selected_guidance_is_isolated_and_traceable():
    full = commerce_design_context()
    selected = commerce_design_context(["data-explanation"])
    assert [g["id"] for g in selected["guides"]] == ["commerce-core", "data-explanation"]
    assert selected["contentSha256"] == full["contentSha256"]  # 标识完整来源包
    selected["guides"].clear()
    assert commerce_design_context(["data-explanation"])["guides"]
```

## Task 2：统一运行时自由模块目录

**Files:** 创建 B `backend/app/application/runtime_module_catalog.py`、B `backend/tests/test_runtime_module_catalog.py`；修改 B `generation_config_service.py`、`module_planning_service.py`、`batch_generation_service.py`、`suite_planning_service.py`、`hero_generation_service.py`（均在 application）；扩展 B `backend/tests/test_generation_config_resolution.py`、`test_batch_generation_compile_service.py`、`test_suite_planning_service.py`。

**Interfaces:**

```python
def runtime_module_catalog(config: dict, mode: str) -> list[dict]: ...
def runtime_catalog_snapshot(config: dict) -> dict: ...
# snapshot = {version: "runtime-modules-v1", contentSha256, heroModules, suiteModules}
# resolve_published() 另附 runtimeModules（该 snapshot），原始 config/hash 不变。
```

- [ ] 写当前工作区发布目录缺少 freeform 的集成测试，捕获实际大师目录，编译 hero-freeform / suite-freeform，验证源配置不变。这是新任务的配置依赖，不涉及旧任务。
- [ ] 运行 `python -m pytest backend/tests/test_runtime_module_catalog.py backend/tests/test_generation_config_resolution.py -q`，确认新增行为失败。
- [ ] 实现 helper：copy 现有数组，仅在缺失时追加 `{id: mode + "-freeform", label: "自由创意", description: "按本图信息目标选择表达方式，商品按需出场", mode}`。重复有效 ID 不追加，错误 mode 返回 `RUNTIME_MODULE_CATALOG_INVALID`。
- [ ] 将上述五处目录解析改为 helper，快照记录 runtime_catalog_snapshot；单主图入口也必须能解析新模块，避免只有批量路径可用。不要 mutate 已发布 record.content。
- [ ] 跑本任务测试及主图/套图编译服务测试；验证 2 个自由任务具有不同 taskId、参数独立、仍只生成各 1 张。
- [ ] 检查并提交：`git commit -m "feat: support freeform commerce image tasks"`。

关键测试：

```python
def test_runtime_catalog_does_not_change_published_config():
    config = {"heroModules": [], "suiteModules": []}
    original = deepcopy(config)
    assert runtime_module_catalog(config, "hero")[-1]["id"] == "hero-freeform"
    assert runtime_module_catalog(config, "suite")[-1]["id"] == "suite-freeform"
    assert config == original
```

## Task 3：大师真正读取设计知识和所选风格

**Files:** 修改 B `backend/app/application/module_planning_service.py`、两份内置规划 SKILL.md、B `backend/app/application/image_style_library.py`；扩展 B `backend/tests/test_module_planning.py`、`test_general_design_planning.py`。修改应用自有 Skill 前读取 writing-for-agents / writing-skills 的适用指引；外部候选 Skill 仍只作为资料。

**Interfaces:** `ModulePlanInput` 增加必传 styleId（可空）、customStyle（最多 2,000 字、可空串）；统一 `MasterOutput` 要求 planningContractVersion=`commerce-design-v1`、sharedVisualDirection；统一 `PlannedModule` 要求 taskTitle、1–2 个 designGuideIds、合法 productPresence，以及原 FreshPlannedModule 的 styleTemplateId/bigIdea/visualMechanism。删除 Fresh/历史宽松模型的分层并更新引用，保留一套严格契约。

- [ ] 更新相关测试 fixture 为完整新响应，缺少必填字段应失败；捕获 f.master.calls 的实际 user_prompt，断言 designKnowledge 和 commerceDesign 内容与 snapshot 一致。无需历史响应兼容测试。
- [ ] 运行 `python -m pytest backend/tests/test_module_planning.py backend/tests/test_general_design_planning.py -q`，确认新增实际注入/契约测试失败。
- [ ] 输入 fingerprint 始终纳入 styleId/customStyle 与新契约版本。使用当前发布配置解析 styleId；未知 ID 返回现有无效风格错误，不忽略。所有前端/测试请求调用点显式传入这两个字段。
- [ ] 在构建请求前只生成一次知识 context，并同时用于请求及 snapshot。传入 selectedStyle={id, description, seed, customStyle}；未指定时为 null。用现有 resolve_style_seed，避免大师和单图使用两套种子。
- [ ] 更新两份 Skill 与 STYLE_LIBRARY_PLANNING_RULES 的输出字段清单及优先级；先规划目标和表达再归类，支持 none，不强制每套使用同一种模板，也不强制凑齐所有表现手法。
- [ ] 停止自动追加“建议构图简案”，不保留旧字段适配路径。未知指南/非法出场枚举进入现有一次纠正再失败机制，不把未校验输出标 completed。不迁移已有记录。
- [ ] 跑上述测试及 `backend/tests/test_image_style_library.py`，检查幂等重放不再次调用模型。
- [ ] 检查并提交：`git commit -m "feat: ground master planning in design guidance"`。

真实接线回归测试主体（沿用现有 fixture）：

```python
@pytest.mark.asyncio
async def test_master_receives_the_knowledge_it_records():
    f = await fixture("hero")
    result = await f.master_service.plan(f.project_id, f.input, "design-context")
    actual = json.loads(f.master.calls[0].user_prompt)
    assert actual["designKnowledge"] == result["snapshot"]["designKnowledge"]
    assert actual["commerceDesign"] == result["snapshot"]["commerceDesign"]
    assert actual["commerceDesign"]["guides"]
```

## Task 4：单图编译尊重任务目标、用户编辑和系列方向

**Files:** 修改 B `backend/app/application/module_planning_v2.py`、`batch_generation_service.py`、`suite_planning_service.py`；创建 B `backend/tests/test_commerce_planning_flow.py`，扩展 `test_module_planning_v2.py`、`test_suite_planning_v2.py`、`test_direct_image_planning_boundaries.py`。

**Interfaces:** `build_v2_compiler_prompts` 新增可选关键字 `shared_visual_direction: str = ""`、`placement: str = "detail"`。user context 增加 commerceDesign、sharedVisualDirection、placement、compositionAdvice、explicitCompositionRequirements；沿用原返回 tuple。在 prompt metadata 记录 design 包版本/hash/IDs。placement 为 primary/gallery/detail，调用方按模式与任务顺序计算。

- [ ] 写 hero 与 suite 捕获编译请求的参数化测试：master none/freeform → compiler none；指南选择正确、系列方向可达、手改参数独立、不新增模型调用。
- [ ] 运行 `python -m pytest backend/tests/test_commerce_planning_flow.py -q`，确认失败。
- [ ] 从自动 task_outline 读取必填 designGuideIds；无大师的手动新任务加载 visual-hierarchy。读取“构图要求”为显式输入，compositionBrief 为建议；均不作为商品事实或 exactCopy。不推断旧“建议构图简案”的编辑来源。
- [ ] 系统规则明确事实/平台 > 用户要求 > 信息目标/出场方式 > 可调整构图/模板建议。显式要求与事实冲突沿用错误/未确认信息路径，不默默造事实。用户明确改变出场方式时需要在请求中明确覆盖原因，不能被默认模块名覆盖。
- [ ] 将默认种子的具体光照与环境从不可变命令改成适配建议；保留选定风格的配色方向和用户明确要求。更新种子版本用于本次新编译快照，不实现历史快照读取适配。
- [ ] 两条服务传入顶层 sharedVisualDirection，并给当前任务算 placement；不改编译后的冻结 prompt、确认和 worker 重试方式。
- [ ] 运行本任务测试及 `backend/tests/test_batch_generation_confirm_service.py backend/tests/test_batch_generation_worker.py backend/tests/test_suite_planning_edit_and_confirm_service.py` 的新任务用例，确保本次创建批次按冻结提示词重试，不额外调用规划模型。
- [ ] 检查并提交：`git commit -m "feat: compile flexible evidence-led image compositions"`。

请求边界测试核心断言：

```python
context = json.loads(captured_request.user_prompt)
assert context["taskOutline"]["productPresence"] == "none"
assert context["placement"] == "gallery"
assert context["explicitCompositionRequirements"] == ["标题放左上角"]
assert [g["id"] for g in context["commerceDesign"]["guides"]] == ["commerce-core", "data-explanation"]
# 该断言验证输入贯通；是否实际补画鼠标由 Task 7 的视觉验收确认。
```

## Task 5：前端新契约请求、恢复及任务状态

**Files:** 修改 F `src/api/client.ts`、`src/lib/planning-master.ts`、`src/lib/generation-workspace.ts`、`src/lib/generation-config.ts`、`src/store/useGenerationConfigStore.ts`，按调用点更新 HeroImageWorkspace/SuiteWorkspace；扩展 F `tests/planning-master.test.ts`、`tests/module-planning-api-client.test.ts`、`tests/generation-config-remote-store.test.ts`、`tests/suite-planning-workspace.test.ts`。

**Interfaces:** API/领域类型补齐设计字段；CommonGenerationConfig 增加 `moduleTaskDetails?: Record<string, {title: string; informationQuestion: string; productPresence: string; visualMechanism: string; compositionAdvice: string}>`，按 taskId 保存展示所需内容。技术指南 IDs 留在服务端，不写入用户参数。

- [ ] 测试新规划不再把自动构图加入参数；styleId/customStyle 改变导致 needsModulePlan=true，迟到响应不能覆盖新配置，只有当前契约且指纹匹配的响应可恢复。
- [ ] 用 `npx tsx --test tests/planning-master.test.ts tests/module-planning-api-client.test.ts tests/generation-config-remote-store.test.ts` 验证新增测试失败。
- [ ] modulePlanRequestInput 发送风格；modulePlanInputFingerprint 加合同版本及风格；canRecoverModulePlan 只接受当前契约。不匹配时要求重新规划，取消旧计划恢复分支。
- [ ] applyModulePlan 统一停止补回“建议构图简案”，保存 moduleTaskDetails；任务删除、重规划、类型改变时清理对应展示状态，保留同任务用户编辑及删除记录。不要把 title 存成会进入 exactCopy 的事实参数。
- [ ] 解析 runtimeModules 到生成用 published 视图，保留原始发布配置 hash 和管理草稿；缺少 runtimeModules 视为配置 API 契约错误，使用现有配置错误展示，不回退旧接口。测试配置编辑/发布不会无意把运行时模块写回。
- [ ] 跑本任务测试及 `npx tsx --test tests/generation-workspace.test.ts tests/suite-planning-workspace.test.ts`、`npm run typecheck`。
- [ ] 检查并提交前端本任务变更：`git commit -m "feat: persist design-led planning tasks and style inputs"`。

测试核心：

```typescript
const planned = applyModulePlan(config, newContractPlan);
assert.equal(planned.moduleParameters["reporting-rate"].some(p => p.key === "建议构图简案"), false);
assert.equal(planned.moduleTaskDetails?.["reporting-rate"].title, "解释回报率");
assert.equal(needsModulePlan({ ...planned, styleId: "future" }), true);
```

`newContractPlan` 在测试文件中由现有 plan fixture 扩展为完整新合同响应，taskId=reporting-rate、moduleId=hero-freeform；config 使用 styleId=minimal，避免断言更换成相同风格。

## Task 6：任务卡表达目标与可编辑建议

**Files:** 修改 F `src/components/generation-workspace/GenerationTaskSelector.tsx`、`src/components/image-canvas/LongImagePlanningAdvice.tsx`；创建 F `tests/generation-task-selector.test.tsx`，更新 F `tests/e2e/module-planning.spec.ts`。

**Interfaces:** 沿用 GenerationTaskSelector 的 config/onChange。显示 moduleTaskDetails；编辑构图写入 moduleParameters[taskId] 的“构图要求”，不修改原始建议。自动任务主标题=taskTitle；手动新增任务以 module.label 初始化标题。

- [ ] 用现有 React 测试方式建立组件测试，验证自动/手动新任务标题、出场中文说明、用户编辑写入“构图要求”、指南 ID 不作为可见文案。
- [ ] 运行 `npx tsx --test tests/generation-task-selector.test.tsx`，确认新增行为失败。
- [ ] 任务卡显示「本图要讲什么」「表达方式」「商品出场」「构图建议」；将商品出场枚举映射为完整/局部/细节/使用情境/不出现。参数编辑入口继续服务用户事实与明确要求。
- [ ] 更新长图顺序建议优先使用 taskTitle；自由模块的多张任务能通过标题区分，删除及重试仍依赖 taskId，不用标题作为身份。
- [ ] 运行组件测试、`npm run build`，并用 stub API 的 `npx playwright test tests/e2e/module-planning.spec.ts` 检查 hero/suite 新任务及刷新恢复。
- [ ] 检查并提交：`git commit -m "feat: show image communication goals in task cards"`。

## Task 7：链路回归与小批视觉对照

**Files:** 创建 B `research/design-guided-planning-evaluation-2026-09-28.md`，完成 B `test_commerce_planning_flow.py` 及 F e2e 场景。此报告在真正执行评测后创建，不预先填入“已改善”。

- [ ] 先运行上述定向测试集合；若发现共享 schema/目录变更影响其他路径，补跑对应现有测试。记录前后端命令、版本及真实结果。
- [ ] Stub 模型覆盖 hero primary/gallery、suite detail、重复 freeform、none、未知指南、错误 module ID、用户手改、风格变更、新批次失败重试。验证两模式共享知识但计划/批次身份独立。
- [ ] 只做提示词编译时，确认无新增付费图片任务；记录实际 system/user 中注入的内容、来源/hash、选定指南、最终 prompt。
- [ ] 执行视觉对照时，使用鼠标与一个非数码商品各 3 类任务（识别、参数解释、使用场景），旧/新各 1 张，共最多 12 张；两组固定同一输入、模型、画幅、分辨率和风格，选取之前冻结旧提示词或在固定旧代码上离线编译。若非数码商品缺可信素材，先完成鼠标 6 张对照并明确通用性未验证，不能编造素材。
- [ ] 实际生成沿用现有用户确认/费用授权流程，实施代码本身不自动创建这些图片。旧图只在生成条件可比时作为基线，否则报告偏差。
- [ ] 人工逐图核对事实/文字/商品身份/表达/系列；none 图不得补回产品，参数图不虚构曲线和指标。记录每张耗时和可得费用；没有费用数据就标“未取得”，不推算已证实成本。
- [ ] 无商品事实错误、要求上图的关键文字准确、新任务目标未被默认模块覆盖，才进入新规划启用；如果失败，按事实/提示词/模型执行分别定位，不先添加自动重试掩盖问题。
- [ ] 检查并提交测试和真实评测记录：`git commit -m "test: verify design-guided commerce planning flow"`。

## 交付与自检

- 前后端按统一的新契约一起交付，不建设新旧客户端混用方案。
- 旧任务不兼容、不迁移、不清理；需要使用新链路时重新规划，不实施任务数据回退适配。
- 执行收尾提供变更范围、测试结果、视觉对照限制、仍未解决问题。无视觉对照时只称“链路已验证”，不称“生图已更好看”。

规划自检映射：知识实际接入 Task 1/3；模块解耦 Task 2；构图/风格/用户优先级 Task 4；风格输入及新任务恢复 Task 5；产品 UI Task 6；证据与回归 Task 7。所有跨任务字段与 helper 在首次使用前定义，第一版无数据库 schema 迁移和新增模型阶段。
