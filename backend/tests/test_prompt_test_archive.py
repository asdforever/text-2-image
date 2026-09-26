from uuid import UUID

import pytest
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.db import create_engine, create_session_factory
from backend.app.minio_utils import MemoryAssetStorage
from backend.app.models.asset import (
    TestProduct as PromptTestProduct,
    TestProductLibrary as PromptTestProductLibrary,
    TestRun as PromptTestRun,
)
from backend.app.models.prompt import PromptTemplate, PromptVersion
from backend.app.test_executor import TestExecutor as PromptTestExecutor


async def _seed_test_run(sessions, suffix: str, *, request_snapshot: dict) -> tuple[UUID, UUID, UUID]:
    async with sessions() as session, session.begin():
        template = PromptTemplate(
            code=f"prompt-test-archive-{suffix}",
            name="白底图测试提示词",
            kind="image_to_image",
            kind_name="图生图",
            stage="plan",
            execution_target="image_model",
        )
        session.add(template)
        await session.flush()
        version = PromptVersion(
            template_id=template.id,
            version_no=1,
            name="白底图测试提示词",
            kind="image_to_image",
            execution_target="image_model",
            body="生成干净的白底商品图",
            user_prompt_template="",
            input_schema=[],
            output_schema={},
            applicability={},
            generation_params={"size": "1024x1024"},
            content_sha256=(suffix[-1] if suffix else "a") * 64,
        )
        session.add(version)
        await session.flush()
        template.default_version_id = version.id
        run = PromptTestRun(
            prompt_version_id=version.id,
            input_text="无线键盘",
            request_snapshot=request_snapshot,
            status="pending",
        )
        session.add(run)
        await session.flush()
        return run.id, template.id, version.id


@pytest.mark.asyncio
async def test_successful_prompt_test_is_archived_once_with_source_snapshot() -> None:
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")
    engine = create_engine(settings.database_url)
    storage = MemoryAssetStorage()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            run_id, template_id, version_id = await _seed_test_run(
                sessions,
                "success",
                request_snapshot={
                    "inputText": "无线键盘",
                    "generationParams": {"size": "1536x1024", "quality": "high"},
                    "model": "fake-image-model",
                },
            )
            executor = PromptTestExecutor(
                sessions,
                storage,
                api_base_url="http://fake.invalid",
                api_key="fake",
                model="fake-image-model",
            )

            await executor._store_result(run_id, b"first-image", "image/png", 1200)
            await executor._store_result(run_id, b"second-image", "image/png", 1300)

            async with sessions() as session:
                run = await session.get(PromptTestRun, run_id)
                products = (
                    await session.execute(
                        select(PromptTestProduct).where(PromptTestProduct.test_run_id == run_id)
                    )
                ).scalars().all()
                library = await session.get(PromptTestProductLibrary, products[0].library_id)
            assert run is not None
            assert run.status == "completed"
            assert len(products) == 1
            assert run.output_product_id == products[0].id
            assert library is not None
            assert library.name == "测试结果"
            assert library.library_type == "test_result"
            assert products[0].extra_metadata == {
                "promptTemplateId": str(template_id),
                "promptTemplateName": "白底图测试提示词",
                "promptVersionId": str(version_id),
                "promptVersionNo": 1,
                "inputAssetId": None,
                "inputText": "无线键盘",
                "generationParams": {"size": "1536x1024", "quality": "high"},
                "model": "fake-image-model",
                "durationMs": 1200,
            }
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_test_run_generation_params_override_prompt_version_defaults() -> None:
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            run_id, _, _ = await _seed_test_run(
                sessions,
                "params",
                request_snapshot={
                    "generationParams": {
                        "size": "1536x1024",
                        "quality": "high",
                    }
                },
            )
            executor = PromptTestExecutor(
                sessions,
                MemoryAssetStorage(),
                api_base_url="http://fake.invalid",
                api_key="fake",
            )

            _, _, input_text, generation_params = await executor._load_inputs(run_id)

            assert input_text == "无线键盘"
            assert generation_params == {
                "size": "1536x1024",
                "quality": "high",
            }
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_prompt_test_does_not_create_test_product() -> None:
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            run_id, _, _ = await _seed_test_run(sessions, "failure", request_snapshot={})

            class FailingExecutor(PromptTestExecutor):
                async def _call_image_api(self, *args, **kwargs):
                    raise RuntimeError("provider unavailable")

            executor = FailingExecutor(
                sessions,
                MemoryAssetStorage(),
                api_base_url="http://fake.invalid",
                api_key="fake",
            )
            await executor.execute(run_id)

            async with sessions() as session:
                run = await session.get(PromptTestRun, run_id)
                product_count = await session.scalar(
                    select(func.count()).select_from(PromptTestProduct).where(
                        PromptTestProduct.test_run_id == run_id
                    )
                )
            assert run is not None
            assert run.status == "failed"
            assert "provider unavailable" in (run.error_message or "")
            assert product_count == 0
            await transaction.rollback()
    finally:
        await engine.dispose()
