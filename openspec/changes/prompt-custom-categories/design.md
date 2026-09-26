## Context

The prompt marketplace currently groups templates by the fixed execution-type values `image_to_image`, `text_to_image`, `text_to_text`, and `image_to_text`. The API and `PromptTemplate` model expose no independent business-category field, while the marketplace already has a list/detail/edit flow that can be extended. See `proposal.md` for the motivation and behavior contract in `specs/prompt-marketplace/spec.md`.

## Goals / Non-Goals

**Goals:**

- Add durable custom category records and an optional association from a prompt template to one category.
- Keep execution type as a separate concept and preserve the existing prompt version workflow.
- Make category filtering and management usable from the existing marketplace page without a separate admin area.
- Make old templates safe to read and edit as uncategorized.

**Non-Goals:**

- Nested categories, multi-category tagging, permissions/roles, or category-specific prompt behavior.
- Replacing execution-type groups or changing prompt version semantics.
- Server-side pagination or a separate search index; the existing list endpoint remains the source for this page.

## Decisions

### Separate category resource and nullable template association

Add a `prompt_categories` table/resource with a UUID identifier, name, sort order, and timestamps. Add a nullable `category_id` foreign key to prompt templates. A nullable relation keeps legacy rows valid and makes “未分类” a stable UI projection rather than a special database row.

Alternative considered: store the category name directly on each template. This was rejected because renames would require a bulk update and duplicate names could diverge.

### REST endpoints mirror existing prompt endpoints

Expose category list/create/update/delete endpoints under `/api/prompt-categories`. Extend prompt template create/update/list payloads with `categoryId` and `categoryName` where applicable. The delete service counts affected templates, nulls their association in the same transaction, then removes the category.

Alternative considered: manage categories entirely in local storage. This would make categories disappear across browsers and would not classify server-created templates, so it is unsuitable for a shared prompt marketplace.

### Client-side filtering with a single category selection

The marketplace loads the category list and templates together, keeps one active category filter, and applies the existing text query after category filtering. The sidebar presents category filters separately from execution-type group labels; the prompt list can still show the execution type as metadata.

Alternative considered: replace the current type groups with categories. This would hide a useful existing distinction and make old templates harder to navigate, so both dimensions remain visible.

### Category management uses a compact inline panel

Use a small management popover/dialog beside the category filter. Creation and rename use the same name validation; deletion shows the affected-template count and requires confirmation. After a mutation, refresh categories and templates while preserving the active category when it still exists.

## Risks / Trade-offs

- [Risk] A category delete can unexpectedly change many templates → show the exact affected count, require confirmation, and make the operation reversible by reassigning templates later.
- [Risk] Existing in-memory repository and SQLAlchemy repository can diverge → add the same category contract to both implementations and cover both route and repository tests.
- [Risk] Long category names make the sidebar noisy → trim and cap names at 40 characters, show counts, and use ellipsis styling with the full name in a tooltip.
- [Risk] Concurrent rename/delete requests can produce stale filters → refresh category/template data after each successful mutation and remove deleted category selections locally before rendering.

## Migration Plan

1. Add the category table and nullable template foreign key migration.
2. Deploy API compatibility fields and category endpoints; old templates read as uncategorized.
3. Deploy the marketplace UI and tests.
4. Roll back the UI independently if needed; rolling back the migration requires removing only the new nullable column/table after category data is no longer in use.
