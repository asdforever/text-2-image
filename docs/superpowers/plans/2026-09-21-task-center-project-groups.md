# Project Task Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the local task-center demo with a read-only project-grouped view of the latest hero and suite generation work.

**Architecture:** The backend returns normalized task summaries from the existing hero-task, generation-batch, and suite-plan repositories. The frontend groups those summaries by project, pins the current project, filters by lifecycle status, refreshes on demand, and navigates to the correct workbench tab. Existing task detail and retry semantics remain owned by the workbench.

**Tech Stack:** FastAPI repositories and routes, TypeScript API client, React, Zustand project store, Node test runner, Playwright.

**Spec:** User-approved chat design: first version covers main-image and detail-suite tasks, grouped by project with the current project pinned.

## Global Constraints

- Task-center reads must not submit compile, confirmation, generation, retry, or cancellation requests.
- Existing project/workbench task state remains the source of truth.
- Unknown or failed provider/model states must be displayed, not converted to empty tasks.
- No database migration is required for the normalized read model.

---

### Task 1: Backend task summary contract

**Files:**
- Create: `backend/app/routes/task_center.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_task_center_api.py`

- [ ] Write route tests for project-scoped hero/suite summaries, empty projects, and workspace isolation.
- [ ] Add `GET /api/task-center` returning normalized project groups with task type, phase, status, progress, timestamps, and error.
- [ ] Read existing repository latest records only; do not invoke compiler, image provider, worker, or mutation service.
- [ ] Register the router and run the focused backend tests.

### Task 2: Frontend API and grouping model

**Files:**
- Modify: `src/api/client.ts`
- Create: `src/lib/task-center.ts`
- Test: `tests/task-center.test.ts`

- [ ] Add typed task-center response models and a GET client method.
- [ ] Add pure grouping, sorting, filtering, and phase-label helpers.
- [ ] Sort current project first, then projects by most recent task update.
- [ ] Add tests for project grouping, current-project pinning, status filtering, and empty groups.

### Task 3: Replace the task-center page

**Files:**
- Modify: `src/pages/TaskCenterPage.tsx`
- Test: `tests/e2e/task-center.spec.ts`

- [ ] Load task summaries from the API with loading, error, empty, and refreshing states.
- [ ] Render project sections and task rows for hero and suite work.
- [ ] Add project/status filters and a refresh button.
- [ ] Navigate to `tab=hero` or `tab=suite` from each row.
- [ ] Remove local fake retry behavior; task-center actions are read-only navigation in this MVP.
- [ ] Add mocked-API browser coverage proving no non-GET requests occur.

### Task 4: Verification

- [ ] Run focused backend tests, unit tests, task-center E2E, typecheck, build, and `git diff --check`.
- [ ] Review the final diff for accidental changes outside task-center scope.
