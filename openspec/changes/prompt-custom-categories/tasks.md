## 1. Data Model And Persistence

- [x] 1.1 Add the prompt category model, nullable prompt-template association, validation constraints, and migration; verify the migration creates the table and preserves legacy templates as uncategorized.
- [x] 1.2 Extend the in-memory and SQLAlchemy prompt repositories with category CRUD, template assignment, affected-template counting, and uncategorization on delete; verify repository tests cover duplicate names and deletion reassignment.

## 2. API Contract

- [x] 2.1 Add category list/create/rename/delete routes with normalized names, duplicate validation, and affected-template counts; verify route tests cover success and validation/error responses.
- [x] 2.2 Extend prompt-template list/detail/create/update responses and request bodies with nullable category fields; verify existing prompt API contract tests still pass and legacy records return an uncategorized value.
- [x] 2.3 Add typed frontend API client methods for category CRUD and category-aware prompt template operations; verify TypeScript compilation and client contract tests.

## 3. Marketplace Experience

- [x] 3.1 Add category state loading, active category filtering, combined category-plus-text search, counts, and empty states to the prompt marketplace; verify component tests cover all, uncategorized, custom, and zero-result views.
- [x] 3.2 Add category management UI for create, rename, and delete with affected-template confirmation and refresh behavior; verify interaction tests cover preserving unrelated selection and clearing a deleted filter.
- [x] 3.3 Add category selection and quick-create affordance to new-template and edit-template forms; verify creating, changing, clearing, and reloading a category association.
- [x] 3.4 Keep execution-type grouping, prompt version actions, batch deletion, and legacy template rendering intact; verify the existing marketplace regression suite passes.

## 4. Verification

- [x] 4.1 Run backend prompt tests and frontend prompt marketplace tests, then verify `npm run typecheck` and `npm run build` complete successfully.
- [x] 4.2 Run the prompt marketplace end-to-end flow and `openspec validate prompt-custom-categories --type change --strict`; verify custom category lifecycle, filtering, and uncategorization on deletion.
