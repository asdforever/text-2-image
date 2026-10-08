# Reverse Plans and Batches Implementation Plan

> **For agentic workers:** Execute inline with executing-plans; read the linked spec first. Keep the existing running project checkout and current feature branch.

**Goal:** Preserve multiple reverse plans and generation batches per product project and display their lineage on the canvas.

**Architecture:** Keep plan JSON documents and introduce a separate revisioned batch repository. Freeze batch inputs before calling the editor, append attempts on retry, and project immutable batch snapshots into existing canvas generation steps.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/Alembic/Postgres, React/TypeScript, existing canvas and image providers.

**Spec:** ../specs/2026-10-07-reverse-plans-batches-design.md

## Global Constraints

- Keep existing plans, assets, published reverse versions, and saved canvas positions.
- Enforce workspace/project/plan membership on every read and mutation.
- A whole generation creates a batch; a retry appends attempts to the same batch.
- Provider input remains product image plus prompt; no reference images.
- No test provider calls or test plans are inserted into the user's database.

## Task 1: Multiple plans

Files: reverse_execution_repository.py, reverse_execution_service.py, routes/reverse_execution.py; tests/test_reverse_execution_repository.py and tests/test_reverse_execution_service.py.

- [x] Add a failing test creating two plans, editing/compiling the first by plan_id, and checking both survive.
- [x] Implement repository list(workspace_id,project_id), get(...,plan_id=None), save(...,plan_id=None), service list/get/name handling and scoped API planId selection.
- [x] Run repository/service/API regression tests.

```python
first = await repository.create(workspace, project, version, {"tasks": []})
second = await repository.create(workspace, project, version, {"tasks": []})
assert [p.id for p in await repository.list(workspace, project)] == [second.id, first.id]
assert (await repository.get(workspace, project, first.id)).id == first.id
```

## Task 2: Persist generation batches and attempts

Files: new reverse_execution_batch_repository.py, new Alembic revision after 20260930_reverse_execution, migration_guard.py, application/reverse_execution_generation_service.py, main.py, routes/reverse_execution.py; new tests/test_reverse_execution_batches.py.

- [x] Write failing flow tests for two whole batches, retry in first batch after changing plan input, partial failure and duplicate-running rejection.
- [x] Implement batch repository list/get/create/save/claim methods with revision checks, plan row lock and batch numbering. In memory mirror Postgres semantics.
- [x] Freeze actual source, product facts, compiled task prompts and model config, clear prior result fields, and persist attempts before/after editor calls.
- [x] Validate task selection and batch scope before external calls. Preserve batches even when updating the current plan conflicts.
- [x] Wire composition and list/detail batch APIs and optional batchId generation input. Run flow and migration checks.

```python
assert len(await service.list_batches(project_id, plan.id)) == 2
assert retried.id == first_batch.id
assert len(retried.document["tasks"][0]["attempts"]) == 2
assert editor.requests[-1].prompt == first_prompt
```

## Task 3: Canvas lineage

Files: application/canvas_lineage.py, routes/workbench.py, main.py, frontend api/client.ts, image-canvas/image-batches.ts and model.ts; new backend lineage tests and frontend image-batches.test.ts.

- [x] Write failing tests proving batch-specific outputs, retry output preservation, source edges, plan labels and no cross-batch contamination.
- [x] Project each task from its batch snapshot; include known available attempts, batch metadata, final prompt and frozen settings. Preserve legacy assets with an explicit unbatched label.
- [x] Include projections in both workbench and canvas step loader. Map reverse images to detail category and render plan/batch labels.
- [x] Run backend lineage and frontend canvas/batch tests.

## Task 4: Plan and batch workspace

Files: frontend api/reverse-execution.ts, pages/ProjectReverseWorkspace.tsx, new pages/ReverseExecutionHistory.tsx, index.css; API client tests and e2e/project-reverse-workspace.spec.ts.

- [x] Extend API types/client for planId, plan list/name and batch list/retry.
- [x] Add plan picker/new form; save dirty inputs before switching; keep selection per project; preserve names/settings when saving.
- [x] Render batch history with frozen task prompts and all attempts; retries pass exact plan and batch IDs; expose project canvas link.
- [x] Ensure failed generation refreshes batch history and archived outputs. Add UI tests for independent switching and original-batch retry.
- [x] Run typecheck, focused frontend tests and production build.

## Task 5: Live rollout and verification

- [x] Verify migration graph/head; upgrade through guarded Alembic workflow, confirm old plan count/IDs survive and batch table is available.
- [x] Restart existing backend hidden and verify ready. Inspect current project's plan list and canvas steps without inserting test data or calling image provider.
- [x] Use browser for real project UI verification; check old plan loads and creation/version options appear.
- [x] Mark tasks complete and report tests, rollout status, and true limitations.

## Verification results

- Backend: 81 passed, 1 skipped (dedicated PostgreSQL test URL unavailable).
- Frontend: 24 unit/integration tests and 6 browser flow tests passed; production build passed.
- Live guarded migration reached 20261007_reverse_batches; all 3 previous plan IDs, revisions and document hashes preserved.
- Live readiness, plan picker, new plan entry and existing canvas lineage verified without model calls or demo records.
- Independent review findings resolved and re-reviewed: current single-image settings, saved revision on failed retry, durable output after archive failure.
