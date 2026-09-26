# 主图与详情套图模块参数 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为主图和详情套图的每个已选模块增加可持久化的推荐/自定义参数，并让这些参数进入规划与生成调用，同时删除主图促销信息模块。

**Architecture:** 在 `generation-workspace.ts` 中集中定义模块参数类型、推荐字段和清理/初始化 helper；`ModuleSelector` 只负责模块选择和渲染已选模块的受控参数编辑器。页面把参数存入现有 Zustand generation draft，套图计划复制同一份模块参数，mock API 接收结构化参数对象。

**Tech Stack:** React 18、TypeScript、Zustand、Node test runner、tsx、Vite。

**Spec:** `docs/superpowers/specs/2026-09-13-generation-module-parameters-design.md`

## Global Constraints

- 参数使用 `Record<moduleId, Array<{ key: string; value: string }>>`，数组顺序即 UI 顺序。
- 每个模块最多 20 行；参数名最多 60 个字符；参数值最多 500 个字符。
- 空参数不阻止生成，传给 mock/后端前过滤空参数名和值。
- 取消选择模块时保留其参数草稿，重新选择后恢复。
- 主图 `promotion`、历史 `designBrief`/`creativePrompt` 只做旧草稿读取兼容，不渲染、不参与生成。
- 不创建分支或 worktree，不提交 commit，直接修改当前 `master` 工作区。

### Task 1: Add module parameter domain model and presets

**Files:**
- Modify: `src/lib/generation-workspace.ts`
- Test: `tests/generation-workspace.test.ts`

**Interfaces:**
- Produces `GenerationModuleParameter`, `GenerationModuleParameters`, `MODULE_PARAMETER_PRESETS`.
- Produces `getModuleParameterPresets(moduleId: string): GenerationModuleParameter[]`.
- Produces `compactModuleParameters(parameters: GenerationModuleParameter[]): GenerationModuleParameter[]`.
- Adds `moduleParameters` to `CommonGenerationConfig` and removes `promotion` from the active `HeroGenerationConfig` defaults.

- [x] **Step 1: Write failing domain tests**

Add tests that expect `normalizeHeroConfig({})` and `normalizeSuiteConfig({})` to contain `moduleParameters: {}`, expect `getModuleParameterPresets("suite-scene")` to include `场景地点`, and expect `compactModuleParameters([{ key: " ", value: "x" }, { key: "DPI", value: "1600" }])` to return only the trimmed DPI row.

- [x] **Step 2: Run the focused tests and verify the expected failure**

Run: `npm test -- --runInBand tests/generation-workspace.test.ts`

Expected: FAIL because the new field and helpers do not exist.

- [x] **Step 3: Implement the model and preset catalog**

Add the shared type and default field. Define recommended fields for all current hero and suite module IDs; modules without a meaningful preset receive `补充说明`. Return a cloned preset array so editing one draft cannot mutate the catalog. Implement `compactModuleParameters` with trimming and blank-row removal.

- [x] **Step 4: Run the focused tests and verify they pass**

Run: `npm test -- --runInBand tests/generation-workspace.test.ts`

Expected: PASS.

### Task 2: Build the reusable module parameter editor

**Files:**
- Create: `src/components/generation-workspace/ModuleParameterEditor.tsx`
- Modify: `src/components/generation-workspace/ModuleSelector.tsx`
- Modify: `src/components/generation-workspace/index.ts`
- Modify: `src/index.css`
- Test: `tests/generation-components.test.tsx`

**Interfaces:**
- `ModuleParameterEditor` consumes `{ module, parameters, onChange }` and emits `GenerationModuleParameter[]`.
- `ModuleSelector` gains optional `moduleParameters` and `onModuleParametersChange(moduleId, parameters)` props; existing callers remain valid when omitted.

- [x] **Step 1: Write failing component tests**

Render `ModuleSelector` with `suite-scene` selected and a parameter map containing `场景地点=办公桌`. Assert the markup includes the module title, `场景地点`, the current value, an `添加参数` control, and no editor for an unselected module. Keep the existing selection-limit assertions intact.

- [x] **Step 2: Run the focused component tests and verify the expected failure**

Run: `npm test -- --runInBand tests/generation-components.test.tsx`

Expected: FAIL because `ModuleSelector` does not render parameter editors.

- [x] **Step 3: Implement the editor and selector integration**

Render one editor below the module grid for each selected module. Initialize missing rows from `getModuleParameterPresets`, support controlled key/value inputs, add up to 20 rows, delete rows, and apply `maxLength` limits. Keep module selection behavior unchanged and preserve parameter maps when a module is deselected.

- [x] **Step 4: Add focused styles and export the component**

Add compact styles for the editor, rows, add/delete controls, and mobile wrapping. Export `ModuleParameterEditor` from the generation-workspace barrel.

- [x] **Step 5: Run the focused component tests and verify they pass**

Run: `npm test -- --runInBand tests/generation-components.test.tsx`

Expected: PASS.

### Task 3: Wire parameters into drafts and remove promotion UI

**Files:**
- Modify: `src/lib/generation-workspace.ts`
- Modify: `src/components/HeroConfigPanel.tsx`
- Modify: `src/components/SuiteConfigPanel.tsx`
- Modify: `tests/generation-pages.test.tsx`
- Modify: `tests/generation-state.test.ts`
- Modify: `tests/generation-workspace.test.ts`

**Interfaces:**
- Both config panels pass `config.moduleParameters` into `ModuleSelector` and persist edits through `onChange`.
- Hero panel no longer renders `促销信息`; legacy values are ignored by the active UI.

- [x] **Step 1: Update tests for the new panel contract**

Change page assertions to require absence of `促销信息`, add assertions for a module parameter editor in both workspaces, and update normalization/state expectations to include `moduleParameters` while removing active promotion expectations.

- [x] **Step 2: Run the affected tests and verify the expected failures**

Run: `npm test -- --runInBand tests/generation-pages.test.tsx tests/generation-state.test.ts tests/generation-workspace.test.ts`

Expected: FAIL because the hero panel still renders promotion and the panels do not pass parameter state.

- [x] **Step 3: Implement panel wiring and promotion removal**

Remove the promotion `ConfigSectionCard` from `HeroConfigPanel`, pass `moduleParameters` and an `onModuleParametersChange` adapter to both selectors, and update normalization defaults without adding promotion back to new configs. Keep unknown persisted keys harmlessly readable for migration compatibility.

- [x] **Step 4: Run the affected tests and verify they pass**

Run: `npm test -- --runInBand tests/generation-pages.test.tsx tests/generation-state.test.ts tests/generation-workspace.test.ts`

Expected: PASS.

### Task 4: Pass module parameters through planning and generation

**Files:**
- Modify: `src/api/fixtures.ts`
- Modify: `src/pages/HeroImageWorkspace.tsx`
- Modify: `src/pages/SuiteWorkspace.tsx`
- Modify: `src/store/useProjectStore.ts`
- Modify: `tests/generation-state.test.ts`
- Modify: `tests/generation-workspace.test.ts`

**Interfaces:**
- `mockGenerateHeroImage` accepts `{ moduleId, moduleParameters }` in addition to existing image options.
- `mockGenerateSuite` accepts optional `{ moduleId, moduleParameters, template, stylePrompt }`.
- `GenerationPlanItem` stores `moduleParameters`.

- [x] **Step 1: Write failing transport tests**

Add a pure assertion around `compactModuleParameters` and plan persistence that a suite plan retains module parameters. Add source-level parameter contract assertions for the mock signatures/call sites if no direct async mock test is practical due fixture delay.

- [x] **Step 2: Run the focused tests and verify the expected failure**

Run: `npm test -- --runInBand tests/generation-state.test.ts tests/generation-workspace.test.ts`

Expected: FAIL because plan items and mock parameter contracts do not include module parameters.

- [x] **Step 3: Implement hero and suite parameter propagation**

Compact the current module rows before each call. For suite planning, copy parameters into each `GenerationPlanItem` and append non-empty values to the visual context. For suite image generation, pass the plan’s parameters. Preserve style parameters and retry behavior.

- [x] **Step 4: Run focused tests and verify they pass**

Run: `npm test -- --runInBand tests/generation-state.test.ts tests/generation-workspace.test.ts`

Expected: PASS.

### Task 5: Full regression verification

**Files:**
- Test: `tests/*.test.ts`, `tests/*.test.tsx`

- [x] **Step 1: Run the complete test suite**

Run: `npm test`

Expected: all tests pass with no failures.

- [x] **Step 2: Run static checks and production build**

Run: `npm run typecheck` and `npm run build`.

Expected: both exit 0. Existing Vite chunk-size/dynamic-import warnings may remain informational.

- [x] **Step 3: Check the final diff for whitespace errors**

Run: `git diff --check`

Expected: no whitespace errors; line-ending warnings are acceptable on this Windows workspace.
