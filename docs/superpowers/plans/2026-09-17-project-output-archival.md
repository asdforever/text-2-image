# 项目生成结果实时归档 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让项目生成结果持久化、实时显示在对应工作区，并自动按项目归档到正式成品库。

**Architecture:** 图片编辑任务与正式产品库增加 PostgreSQL adapter；项目成品归档模块隐藏“查找/创建项目产品、版本去重、来源快照写入”的复杂性。白底图与批次 Worker 在项目资产写入成功后调用该模块，前端仅从项目详情和成品库读取结果。

**Tech Stack:** FastAPI、SQLAlchemy async、PostgreSQL、Alembic、React、TypeScript、pytest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-17-project-output-archival-design.md`

## Global Constraints

- 所有用户可见文案、注释和文档使用中文。
- 不修改测试库自动归档语义。
- 不复制对象存储图片；正式版本只保存受控引用与不可变来源快照。
- 每项目一个自动产品条目，同来源成功输出幂等归档。
- 不重置或回退当前脏工作区中的无关修改。

---

### Task 1: 图片编辑 PostgreSQL 仓储

**Files:**
- Create: `backend/app/image_editing_sqlalchemy_repository.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_image_editing_postgres_repository.py`

**Interfaces:**
- Consumes: `ImageEditSessionRecord`、`ImageEditTaskRecord`、`ImageEditAttemptRecord`、`ImageEditVersionRecord`。
- Produces: 与 `InMemoryImageEditingRepository` 相同的会话、任务、重试、版本与选择接口。

- [ ] **Step 1: 写入失败测试**

```python
async def test_image_edit_task_and_version_survive_repository_recreation(session_factory):
    first = SqlAlchemyImageEditingRepository(session_factory)
    task = await first.create_task(...)
    await first.add_version(task.id, version)
    restored = await SqlAlchemyImageEditingRepository(session_factory).get_task(task.id, workspace_id)
    assert restored.status == "succeeded"
    assert restored.versions[0].id == version.id
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_image_editing_postgres_repository.py -q`
Expected: FAIL，因为 PostgreSQL adapter 尚不存在。

- [ ] **Step 3: 实现最小 PostgreSQL adapter 并在运行时注入**

```python
resolved_image_editing_repository = image_editing_repository or (
    SqlAlchemyImageEditingRepository(session_factory)
    if session_factory is not None else InMemoryImageEditingRepository()
)
```

- [ ] **Step 4: 运行仓储测试**

Run: `python -m pytest backend/tests/test_image_editing_postgres_repository.py backend/tests/test_image_editing_service.py -q`
Expected: PASS。

### Task 2: 正式产品库 PostgreSQL 与项目归档模块

**Files:**
- Create: `backend/app/product_library_sqlalchemy_repository.py`
- Create: `backend/app/application/project_output_archive_service.py`
- Modify: `backend/app/application/product_library_service.py`
- Modify: `backend/app/main.py`
- Modify: `alembic/versions/<new_revision>_add_project_product_uniqueness.py`
- Test: `backend/tests/test_project_output_archive_service.py`

**Interfaces:**
- Consumes: `archive_output(project_id, product_type, source_version_id, object_key, preview_url, source_snapshot, prompt_snapshot, config_snapshot, idempotency_key)`。
- Produces: 每项目唯一产品与幂等的 `ProductVersion`。

- [ ] **Step 1: 写入失败测试**

```python
async def test_archive_output_creates_one_product_per_project_and_deduplicates_source():
    first = await archive.archive_output(project_id, "white_background", source_version_id, ...)
    replay = await archive.archive_output(project_id, "white_background", source_version_id, ...)
    assert first.id == replay.id
    assert len(await repository.list_project_products(project_id)) == 1
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_project_output_archive_service.py -q`
Expected: FAIL，因为归档模块不存在。

- [ ] **Step 3: 实现 PostgreSQL repository、项目唯一约束和归档模块**

```python
async def archive_output(...):
    product = await self.repository.get_or_create_project_product(project_id, project_name)
    return await self.repository.get_or_create_output_version(product.id, source_version_id, product_type, ...)
```

- [ ] **Step 4: 运行归档与迁移测试**

Run: `python -m pytest backend/tests/test_project_output_archive_service.py backend/tests/test_product_library_service.py -q`
Expected: PASS。

### Task 3: 成功 Worker 实时写入项目与成品

**Files:**
- Modify: `backend/app/application/image_editing_worker.py`
- Modify: `backend/app/application/batch_generation_worker.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_image_editing_worker.py`
- Test: `backend/tests/test_batch_generation_worker.py`

**Interfaces:**
- Consumes: Task/slot 成功结果和 Task/Batch 快照。
- Produces: 项目资产与自动归档成品版本；任一归档失败不标记成功。

- [ ] **Step 1: 写入失败测试**

```python
async def test_white_background_worker_writes_project_asset_and_project_product_version():
    await worker.process_task(task.id)
    assert await assets.list_assets(project.id)
    assert (await archive.list_versions_for_project(project.id))[0].product_type == "white_background"
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_image_editing_worker.py backend/tests/test_batch_generation_worker.py -q`
Expected: FAIL，因为 Worker 尚未调用归档模块。

- [ ] **Step 3: 在白底图和批次成功分支调用归档模块**

```python
await self.project_output_archive.archive_output(
    project_id=...,
    product_type=...,
    source_version_id=...,
    object_key=...,
    preview_url=...,
    source_snapshot=...,
    prompt_snapshot=...,
    config_snapshot=...,
    idempotency_key=f"generated:{source_version_id}",
)
```

- [ ] **Step 4: 运行 Worker 回归测试**

Run: `python -m pytest backend/tests/test_image_editing_worker.py backend/tests/test_batch_generation_worker.py backend/tests/test_hero_generation_confirm_service.py -q`
Expected: PASS。

### Task 4: 成品库按项目浏览与工作区刷新

**Files:**
- Modify: `backend/app/routes/product_library.py`
- Modify: `src/pages/ProductLibraryDetailPage.tsx`
- Modify: `src/pages/BaseImageWorkspace.tsx`
- Modify: `src/api/client.ts`
- Test: `tests/product-library-page.test.tsx`
- Test: `tests/e2e/image-editing-product-flow.spec.ts`

**Interfaces:**
- Consumes: 项目关联产品、已归档产品版本、项目资产刷新接口。
- Produces: 成品库按项目显示，白底图完成后自动刷新项目工作区。

- [ ] **Step 1: 写入失败测试**

```typescript
test("项目成品库按项目显示自动归档版本且不要求手填版本标识", () => {
  const html = renderToStaticMarkup(<ProductLibraryDetailPage />);
  assert.doesNotMatch(html, /成功版本标识/);
});
```

- [ ] **Step 2: 运行失败测试**

Run: `npm test -- tests/product-library-page.test.tsx`
Expected: FAIL，因为页面仍要求手工填写来源版本。

- [ ] **Step 3: 改为项目成品浏览界面并保留受控预览**

```tsx
<Button onClick={() => navigate({ to: "/projects/$projectId", params: { projectId: product.projectId }, search: { tab: "base" } })}>
  打开项目
</Button>
```

- [ ] **Step 4: 运行前端专项验证**

Run: `npm test -- tests/product-library-page.test.tsx && npx playwright test tests/e2e/image-editing-product-flow.spec.ts`
Expected: PASS。

### Task 5: 数据库迁移、全量验证与中文交付记录

**Files:**
- Modify: `docs/image-editing-and-product-library-delivery.md`
- Test: `backend/tests/test_image_editing_migration.py`
- Test: `backend/tests/test_product_library_models.py`

- [ ] **Step 1: 写入迁移链测试**

```python
def test_project_product_uniqueness_migration_is_in_upgrade_chain():
    assert "uq_products_workspace_project" in MIGRATION.read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_image_editing_migration.py -q`
Expected: FAIL，因为唯一约束迁移尚未加入。

- [ ] **Step 3: 写入迁移和交付记录**

```sql
CREATE UNIQUE INDEX uq_products_workspace_project
ON project_workbench.products(workspace_id, project_id)
WHERE project_id IS NOT NULL AND archived_at IS NULL;
```

- [ ] **Step 4: 运行最终验证**

Run: `python -m pytest backend/tests -q && npm test && npm run build`
Expected: 全部通过。
