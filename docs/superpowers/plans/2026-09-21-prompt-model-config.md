# Prompt Model Configuration Implementation Plan

**Goal:** Add a dedicated language-model configuration to the existing generation configuration screen, used by shared style and independent module planning.

**Architecture:** Reuse immutable encrypted model connections with a new `openai_chat` protocol. Generation config has `promptModel: {connectionId: string} | null`; absence/null uses the existing context environment settings. Each new planning task resolves one published connection, freezes non-secret connection metadata, and uses it for every style/module call. Image model selection remains separate.

**Spec:** Current user request: 在生成配置里加入生成提示词的大语言模型配置. The authorized implementation adds one active prompt model, edited with Base URL, model name and API key through the existing draft/publish flow.

**Global constraints:** Preserve existing working changes and previously completed style planning. No secrets in draft/config/task responses/browser persistence. Blank edit key reuses the existing key. Publishing validates protocol and workspace ownership. A running task must not switch model when another config is published. No paid provider requests during validation; isolate tests from the live .env database.

## Task 1 — backend configuration and runtime

- [x] Test chat connection create/list/key reuse, config roundtrip and publish validation, all planning consumers using frozen model, fallback and protocol separation.
- [x] Extend connection service and DB check constraint for `openai_chat`; accept base URL with/without `/v1` for this provider.
- [x] Add nullable promptModel normalization and publish validation; wire style/hero/batch/suite runtime to one frozen published prompt model per task.
- [x] Validate targeted tests and document migration.

## Task 2 — generation config UI

- [x] Add optional nullable promptModel type and store update; verify draft/publish roundtrip and no credential persistence.
- [x] Add 提示词模型 section with current model, existing chat connection selector, add/edit connection form, environment fallback.
- [x] Explain use by style/module planning, multimodal requirement and publish lifecycle; keep image configuration independent.
- [x] Run focused store/UI tests and frontend build.

## Task 3 — integrate and verify

- [x] Independently review affected behavior and fixes.
- [x] Apply additive local schema migration, reload backend as needed; read-only verify config APIs without changing selected model or invoking paid models.
- [x] Record evidence and deliver usage instructions.
