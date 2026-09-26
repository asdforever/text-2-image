# 通用电商视觉规划知识库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为主图和详情套图增加通用设计知识、任务级版式约束和生成后审稿，使规划结果跨品类保持层级、节奏、可读性和商品真实性。

**Architecture:** 新增版本化通用设计知识包与案例卡片 schema。规划大师产出套图叙事和每图版式约束，模块规划器消费这些约束生成单图提示词，设计审稿器对规划和生成结果执行硬性规则与 20 分制评分。第一阶段使用静态知识包，不引入向量数据库或在线抓取。

**Tech Stack:** Python/FastAPI/Pydantic, React/TypeScript, pytest, existing planning snapshot persistence.

**Spec:** [2026-09-23-general-ecommerce-design-knowledge-design.md](../specs/2026-09-23-general-ecommerce-design-knowledge-design.md)

## Global Constraints

- 通用规则必须适用于至少三个品类；鼠标案例只能作为覆盖层。
- 历史规划快照保持可读取，新增字段缺失时使用兼容默认值。
- 不允许模块规划器覆盖 `productPresence`、`layoutFamily`、`informationQuestion` 和 `avoid`。
- 规则、案例引用和审稿结果必须可追溯到版本和哈希。
- 生成提示词不得编造商品参数、功能、认证或比较结论。

### Task 1: 建立通用设计知识模型

**Files:**
- Create: `backend/app/application/design_knowledge.py`
- Create: `backend/app/data/design_knowledge_v1.json`
- Test: `backend/tests/test_design_knowledge.py`

**Interfaces:**
- Produces `DesignKnowledgePack`, `DesignSetPlan`, `DesignImagePlan`, `DesignCaseCard` 和 `DesignReviewResult` 的 Pydantic 模型。
- Produces `load_design_knowledge(version: str = "v1") -> DesignKnowledgePack`。

- [ ] **Step 1: Write failing tests** for required fields, enum values, version/hash and compatibility defaults.
- [ ] **Step 2: Run** `pytest backend/tests/test_design_knowledge.py -q` and verify failure.
- [ ] **Step 3: Implement** the models and static v1 loader with the general rules from the research note.
- [ ] **Step 4: Run** the same test and verify pass.
- [ ] **Step 5: Commit** `feat: add general ecommerce design knowledge model`.

### Task 2: Extend planning output with visual constraints

**Files:**
- Modify: `backend/app/skills/hero-planning-master/SKILL.md`
- Modify: `backend/app/skills/suite-planning-master/SKILL.md`
- Modify: `backend/app/application/suite_planning_service.py`
- Modify: `backend/app/application/module_planning_v2.py`
- Test: `backend/tests/test_general_design_planning.py`

**Interfaces:**
- Consumes `DesignKnowledgePack` and emits set-level `visualRhythm`, `productPresencePlan`, `layoutFamilies` plus task-level `informationQuestion`, `productPresence`, `subjectScale`, `layoutFamily`, `evidence`, `previousModuleContrast`, and `avoid`.
- `build_v2_compiler_prompts` accepts the task visual constraints without changing existing snapshot validation.

- [ ] **Step 1: Add failing tests** proving task constraints survive planner serialization and enter compiler context.
- [ ] **Step 2: Run** `pytest backend/tests/test_general_design_planning.py -q` and verify failure.
- [ ] **Step 3: Update** skills and prompt context with the general design fields and the rule that full product is conditional.
- [ ] **Step 4: Run** focused planning and module-planning tests.
- [ ] **Step 5: Commit** `feat: pass visual design constraints through planning`.

### Task 3: Add design review rules

**Files:**
- Create: `backend/app/application/design_review.py`
- Test: `backend/tests/test_design_review.py`

**Interfaces:**
- Produces `review_design_set(plans, generated_metadata) -> DesignReviewResult`.
- Returns hard failures, per-category scores, total score and actionable reasons.

- [ ] **Step 1: Write failing tests** for repeated full-product hero shots, repeated camera/layout, missing evidence, low contrast and mobile readability.
- [ ] **Step 2: Run** `pytest backend/tests/test_design_review.py -q` and verify failure.
- [ ] **Step 3: Implement** deterministic checks using the design pack; keep image pixels optional in v1 and evaluate available generation metadata first.
- [ ] **Step 4: Run** focused review tests and existing planning tests.
- [ ] **Step 5: Commit** `feat: add ecommerce design review rules`.

### Task 4: Persist and display planning provenance

**Files:**
- Modify: `backend/app/application/suite_planning_confirmation_service.py`
- Modify: `backend/app/application/batch_generation_service.py`
- Modify: `src/api/client.ts`
- Modify: `src/hooks/useModulePlanning.ts`
- Test: `backend/tests/test_suite_planning_v2.py`
- Test: `src/lib/__tests__/planning-master.test.ts`

**Interfaces:**
- Snapshots include `designKnowledgeVersion`, `designKnowledgeSha256`, task visual constraints, case references and review result.
- Existing snapshots without provenance remain readable.

- [ ] **Step 1: Add failing snapshot tests** for provenance persistence and legacy defaults.
- [ ] **Step 2: Run** focused backend and frontend tests and verify failure.
- [ ] **Step 3: Implement** snapshot fields and API types without changing existing confirmation behavior.
- [ ] **Step 4: Run** focused tests plus TypeScript checks.
- [ ] **Step 5: Commit** `feat: persist design planning provenance`.

### Task 5: Add cross-category fixtures and verification

**Files:**
- Create: `backend/tests/fixtures/general_design_cases.json`
- Modify: `backend/tests/test_batch_generation_compile_service.py`
- Modify: `research/general-ecommerce-image-design-research.md`

- [ ] **Step 1: Add fixtures** for electronics, home goods and beauty/packaging with distinct visual roles.
- [ ] **Step 2: Add tests** verifying the same schema handles all three categories and avoids repeated full-product composition.
- [ ] **Step 3: Run** focused backend tests, the frontend test suite relevant to planning, and production build.
- [ ] **Step 4: Record** verification output and known limitations in the research note.
- [ ] **Step 5: Commit** `test: verify general design rules across categories`.
