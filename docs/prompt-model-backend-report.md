# Prompt model backend implementation — 2026-09-21

Task 1 of `docs/superpowers/plans/2026-09-21-prompt-model-config.md` is implemented. Existing shared-style and other working changes were preserved. This backend task did not modify frontend files, apply a database migration, create commits, or invoke a live model.

## Resulting contract

- Generation config accepts `promptModel: {connectionId: string} | null`. Missing/null retains `context_base_url`, `context_model`, and `context_api_key` fallback. Normalization rejects other fields, including credentials.
- Model connections support `openai_chat` and `openai_images`. The existing create endpoint accepts `baseUrl`, `modelName`, `protocol`, `apiKey`, and `reuseConnectionId`. A blank key reuses an owned connection of the same protocol. Each edit creates an immutable encrypted connection version.
- List responses expose only redacted metadata. Configured context settings appear as `environment-context` with `openai_chat`; image environment remains `environment` with `openai_images`.
- Publish validates explicitly selected prompt connection ownership and protocol. A missing connection service fails closed. Image snapshots and image resolution reject chat connections.
- Hero, batch, and suite planning resolve the prompt model once using the same published config already read for the task. They bind task-local style/compiler providers and freeze non-secret `promptModelConnection` metadata on the task and relevant module snapshots. All style + module calls use that connection even if a different config is published or context settings change in flight.
- Injected fake/custom ports remain independent, including partial injection where only style or module compilation is a fake. Fully injected fakes do not require real model credentials.
- Chat endpoints add `/v1` for a root URL. An explicit API path is preserved: `/v1`, `/api/v3`, or `/openai` receives `/chat/completions` directly.

## Files changed by this task

- `backend/app/application/model_connection_service.py`: chat connection creation, safe key reuse, environment listing/freezing, chat resolution, image/chat separation, malformed input validation.
- `backend/app/generation_config_catalog.py` and `backend/app/application/generation_config_service.py`: nullable prompt selection normalization and publish validation.
- `backend/app/providers/configured_prompt_models.py`: new per-task resolver and bound provider bundle.
- `backend/app/providers/openai_compatible.py`: task-local connection binding and common chat endpoint normalization for all three providers.
- `backend/app/application/hero_generation_service.py`, `batch_generation_service.py`, and `suite_planning_service.py`: one binding per task and frozen metadata.
- `backend/app/main.py`: resolver composition independent of image provider injection.
- `backend/app/migration_guard.py`: expected head updated to `a8b9c0d1e2f3`.
- `alembic/versions/a8b9c0d1e2f3_add_prompt_model_connections.py`: additive protocol constraint update after `f7a8b9c0d1e2`.
- `backend/tests/test_prompt_model_config.py` and `backend/tests/test_prompt_model_runtime.py`: 44 focused cases.

## Verification

TDD evidence: the first configuration run failed all 10 initial cases for missing protocol/config support; the runtime red run failed endpoint and resolver/consumer wiring cases; subsequent malformed-input and unavailable-service cases failed before their fixes. Review identified explicit custom API prefix compatibility; six new provider cases failed before the root-only `/v1` adjustment. Existing migration layout test caught the stale expected head before its update.

Final targeted regression command, run from the repo root:

```powershell
python -c "from backend.app.core.config import Settings; Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main(['backend/tests/test_prompt_model_config.py','backend/tests/test_prompt_model_runtime.py','backend/tests/test_model_connections.py','backend/tests/test_generation_model_connections.py','backend/tests/test_generation_config_security.py','backend/tests/test_generation_config_resolution.py','backend/tests/test_generation_config_repository.py','backend/tests/test_generation_config_prompt_bindings.py','backend/tests/test_generation_config_idempotent_replay.py','backend/tests/test_generation_config_catalog.py','backend/tests/test_generation_config_service.py','backend/tests/test_generation_config_api.py','backend/tests/test_generation_config_bootstrap.py','backend/tests/test_hero_generation_compile_service.py','backend/tests/test_batch_generation_compile_service.py','backend/tests/test_suite_planning_service.py','backend/tests/test_shared_style_planning.py','backend/tests/test_style_planning_repository.py','backend/tests/test_style_planner_provider.py','backend/tests/test_prompt_compiler_provider.py','backend/tests/test_planning_template_boundaries.py','backend/tests/test_direct_image_planning_boundaries.py','backend/tests/test_hero_generation_bootstrap.py','backend/tests/test_batch_generation_bootstrap.py','backend/tests/test_alembic_layout.py','-q','--tb=short']))"
```

Result: **182 passed in 4.71s**, exit 0. All tests isolate `.env`; new settings also explicitly disable database configuration. HTTP uses `httpx.MockTransport`, persistence uses memory repositories. No live database or model requests were made.

The concurrency integration cases cover all three planning consumers and three selection modes (explicit connection, null fallback, explicit environment connection). An old task blocks inside its style HTTP call, another model is published, and a new task completes before the old task resumes. Assertions verify HTTP URL/model/authentication, exactly 1 + N calls per task, stable task/module snapshots, compiled outputs, and idempotent replay without more calls.

`git diff --check` exited 0; Git printed existing LF-to-CRLF notices only.

## Migration handoff

Offline SQL verification command:

```powershell
python -c "from backend.app.core.config import Settings; Settings.model_config['env_file']=None; from alembic.config import Config; from alembic import command; c=Config('alembic.ini'); c.set_main_option('sqlalchemy.url','postgresql+asyncpg://test:test@localhost/test'); command.upgrade(c,'f7a8b9c0d1e2:a8b9c0d1e2f3',sql=True)"
```

Result: exit 0. Output is a transaction that drops `generation_config.model_connections`' existing `model_connections_protocol_check`, recreates it as `protocol IN ('openai_images', 'openai_chat')`, and advances Alembic version. No data deletion or table replacement. Downgrade intentionally fails if retained chat rows violate the old image-only constraint; it never deletes those immutable records.

The root task owns applying this migration and restarting/verifying the local API. No selected configuration was changed by this backend implementation task.
