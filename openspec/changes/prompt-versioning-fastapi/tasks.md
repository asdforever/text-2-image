## 1. FastAPI and dependency boundary

- [x] 1.1 Replace the provisional custom migration entrypoint with Alembic configuration and an async migration environment; verify `alembic upgrade head --sql` renders without importing `pic_agent_suite_workbench` (live `alembic check` awaits database availability).
- [x] 1.2 Add SQLAlchemy prompt models, shared declarative metadata, and async session wiring; verify model imports and `python -m compileall -q backend` pass.
- [x] 1.3 Remove root runtime scripts and configuration references that start or proxy to the old Node service; verify `rg "pic_agent_suite_workbench|3001" backend src vite.config.ts package.json` returns no runtime references.

## 2. Database baseline and reset

- [x] 2.1 Create Alembic baseline migration for the FastAPI suite/input-image tables required by the existing scaffold; verify a clean development database reaches `alembic upgrade head` successfully.
- [x] 2.2 Create prompt template/version tables, constraints, indexes, immutable-version trigger, and sync-status fields; verify migration SQL/model metadata includes unique template codes and `(template_id, version_no)`.
- [x] 2.3 Implement guarded `db-reset --confirm-reset` that only operates in development and runs `alembic upgrade head`; verify it refuses missing confirmation or non-development settings without changing the database.
- [x] 2.4 Execute the full reset only after confirming the `.env` target is a disposable development database; verify the resulting schema contains no legacy prompt rows and all baseline tables are queryable.

## 3. Prompt repository and service

- [x] 3.1 Implement repository operations for aggregate listing, template lookup, version listing, and explicit version lookup using async SQLAlchemy; verify repository tests cover default and historical version retrieval.
- [x] 3.2 Implement transactional creation of a new template/version with row locking, sequential version allocation, content-hash deduplication, metadata capture, and default-version update; verify concurrent creation tests preserve unique sequential numbers.
- [x] 3.3 Enforce version immutability in service validation and database trigger handling; verify update/delete attempts on saved versions return a conflict and leave the row unchanged.
- [x] 3.4 Implement version resolution that defaults to the template default version and rejects a version belonging to another template; verify explicit historical selection does not change the default pointer.

## 4. Markdown file store and import

- [x] 4.1 Implement UTF-8 Markdown parsing/rendering for frontmatter and required prompt sections under the root `prompt/` directory; verify valid files round-trip without content loss and malformed files produce file-scoped errors.
- [x] 4.2 Implement `prompt-import` CLI scanning only root `prompt/`, creating v1 for new codes and a new version for changed hashes; verify an empty directory leaves the database empty and legacy directory files are ignored.
- [x] 4.3 Implement atomic same-directory temporary-file writes with flush/fsync and replace semantics; verify a successful sync leaves exactly one latest file per code and no partial temporary file.
- [x] 4.4 Add sync-status persistence (`pending`, `synced`, `failed`), error capture, and idempotent retry service/CLI; verify injected filesystem failures preserve the database version and a retry repairs the file without creating another version.

## 5. FastAPI prompt endpoints

- [x] 5.1 Add request/response schemas and routes for template list, template detail, version history, and full version detail; verify API contract tests return one aggregate item per code and complete audit metadata in history.
- [x] 5.2 Add create-template and create-version routes supporting edits from any historical version, optional change notes, and duplicate-content errors; verify responses include new version, default version, and file sync status.
- [x] 5.3 Add version-resolution contract for future generation callers and explicit sync-retry route; verify invalid ownership and retry errors use the standard response envelope.
- [x] 5.4 Register prompt routes in the FastAPI application factory and keep in-memory repository support for unit tests; verify the existing health/readiness and suite tests remain green.

## 6. Frontend marketplace and API client

- [x] 6.0 Add an empty-state “new prompt” form and create action; verify the form validates required metadata and creates v1 through `createPromptTemplate`.
- [x] 6.1 Update the frontend API client types and methods to consume FastAPI aggregate/template/version endpoints; verify TypeScript typecheck passes without old Node prompt routes.
- [x] 6.2 Refactor the marketplace list to render one card per template with default version and version count; verify UI contract tests cover search and aggregate rendering.
- [x] 6.3 Add template detail version history with source, change note, timestamps, default marker, and sync status; verify selecting an older version displays its immutable content.
- [x] 6.4 Add editor flow with unsaved draft state, “save as new version”, optional change note, historical-version editing, and sync-retry feedback; verify component tests cover v1 -> v2 creation and failed sync messaging.
- [x] 6.5 Add version selector data contract for generation callers, defaulting to latest while preserving explicit historical selection; verify selected `templateVersionId` is sent without changing the default template.

## 7. Verification and handoff

- [x] 7.1 Add Python tests for models, repository concurrency, service validation, Markdown parsing, file atomicity, sync failure/retry, and API envelopes; verify `python -m pytest` passes (21 passed, 1 integration skipped pending external services).
- [x] 7.2 Add frontend contract tests for aggregate marketplace, version history, editor save, and version selection; verify `npm test` and `npm run typecheck` pass.
- [x] 7.3 Run UTF-8 and security hygiene checks, confirming no credentials are logged or committed and no runtime code references the old directory; verify `npm run check:encoding` and repository scans pass.
- [x] 7.4 Run strict OpenSpec validation and document the dedicated development database reset/migration evidence; verify `openspec validate prompt-versioning-fastapi --type change --strict` passes before implementation handoff.
