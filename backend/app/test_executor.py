"""异步测试执行器：读取提示词 + 素材 → 调用 gpt-image-2 → 存储结果"""
import asyncio
import base64
import io
import logging
import time
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models.asset import Asset, TestProduct, TestProductLibrary, TestRun
from .models.prompt import PromptVersion
from .application.model_connection_service import image_endpoint

logger = logging.getLogger("picagent.test_executor")


class TestExecutor:
    """Handles async execution of prompt test runs against gpt-image-2."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        asset_storage,
        *,
        api_base_url: str,
        api_key: str,
        model: str = "gpt-image-2",
    ):
        self.session_factory = session_factory
        self.asset_storage = asset_storage
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.model_connections = None

    async def execute(self, test_run_id: UUID) -> None:
        """Run a single test: load inputs, call LLM, store result."""
        start = time.monotonic()
        try:
            await self._set_status(test_run_id, "running")

            # 1. Load test run + prompt + asset
            prompt_body, image_b64, input_text, generation_params = await self._load_inputs(test_run_id)

            # 2. Call gpt-image-2
            result_b64, result_mime = await self._call_image_api(
                prompt_body, image_b64=image_b64, input_text=input_text, generation_params=generation_params
            )

            # 3. Store result
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._store_result(test_run_id, result_b64, result_mime, duration_ms)

        except Exception:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "test run failed",
                extra={"test_run_id": str(test_run_id)},
            )
            await self._set_status(
                test_run_id, "failed",
                error_message="测试生图失败，请检查模型连接、输入图片和生成参数",
                duration_ms=duration_ms,
            )

    async def _load_inputs(self, test_run_id: UUID) -> tuple[str, str | None, str | None, dict]:
        """Load prompt body, asset image base64 (if any), input text (if any), and generation params."""
        async with self.session_factory() as session, session.begin():
            run = await session.get(TestRun, test_run_id)
            if not run:
                raise ValueError(f"TestRun {test_run_id} not found")

            version = await session.get(PromptVersion, run.prompt_version_id)
            if not version:
                raise ValueError(f"PromptVersion {run.prompt_version_id} not found")

            from .application.prompt_usage import require_image_prompt
            require_image_prompt(version)
            prompt_body = version.body
            generation_params = dict(version.generation_params or {})
            request_params = (run.request_snapshot or {}).get("generationParams")
            if isinstance(request_params, dict):
                generation_params.update(request_params)
            connection = (run.request_snapshot or {}).get("modelConnection")
            if connection:
                generation_params["modelConnection"] = connection
            image_b64 = None
            input_text = run.input_text

            if run.input_asset_id:
                asset = await session.get(Asset, run.input_asset_id)
                if asset and asset.minio_key and self.asset_storage:
                    # Download image and convert to base64
                    image_bytes = await self.asset_storage.download_file(asset.minio_key)
                    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                elif asset and asset.content:
                    input_text = asset.content

        return prompt_body, image_b64, input_text, generation_params

    async def _call_image_api(
        self,
        prompt: str,
        *,
        image_b64: str | None = None,
        input_text: str | None = None,
        generation_params: dict | None = None,
    ) -> tuple[bytes, str]:
        """Call gpt-image-2 API. Returns (image_bytes, mime_type)."""
        if generation_params is None:
            generation_params = {}

        api_base_url, api_key, model = self.api_base_url, self.api_key, self.model
        if self.model_connections is not None:
            frozen = generation_params.get("modelConnection")
            connection = await self.model_connections.resolve(frozen) if frozen else self.model_connections.environment()
            api_base_url, api_key, model = connection.base_url, connection.api_key, connection.model_name

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Build the prompt: system body + optional input text
        full_prompt = prompt
        if input_text:
            full_prompt = f"{prompt}\n\n用户输入:\n{input_text}"

        # Build base payload with configured parameters
        payload = {
            "model": model,
            "prompt": full_prompt,
            "n": 1,
            "size": generation_params.get("size", "1024x1024"),
            "response_format": "b64_json",
        }

        # Add optional parameters if present
        if "quality" in generation_params:
            payload["quality"] = generation_params["quality"]
        if "style" in generation_params:
            payload["style"] = generation_params["style"]
        if "seed" in generation_params:
            payload["seed"] = generation_params["seed"]
        if generation_params.get("background") == "transparent":
            payload["background"] = "transparent"
            payload["output_format"] = "png"

        # Add image for image-to-image workflow (base64 encoded)
        if image_b64:
            payload["image"] = image_b64

        try:
            # Create client with trust_env=False to disable system proxy
            async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
                url = image_endpoint(api_base_url, "generations")
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise ValueError("模型接口请求超时") from None
        except httpx.HTTPStatusError as e:
            raise ValueError(f"模型接口返回错误，状态码 {e.response.status_code}") from None
        except Exception:
            raise ValueError("模型接口请求失败") from None

        # Extract the image from response
        image_data = data.get("data", [{}])[0]
        b64 = image_data.get("b64_json", "")
        if not b64:
            raise ValueError("API 未返回图片数据")

        image_bytes = base64.b64decode(b64)
        if generation_params.get("background") == "transparent":
            from .core.transparent_image import transparent_png
            image_bytes = transparent_png(image_bytes)
        return image_bytes, "image/png"

    async def _store_result(
        self,
        test_run_id: UUID,
        image_bytes: bytes,
        mime_type: str,
        duration_ms: int,
    ) -> None:
        """Upload result image to MinIO, create Product, update TestRun."""
        async with self.session_factory() as session:
            run = await session.get(TestRun, test_run_id)
            if run is None:
                return
            existing = await session.scalar(
                select(TestProduct).where(TestProduct.test_run_id == test_run_id)
            )
            if existing is not None:
                run.output_product_id = existing.id
                run.status = "completed"
                return

        # Upload to MinIO
        ext = "png" if "png" in mime_type else "jpg"
        bucket, key, file_type, file_size = await self.asset_storage.upload_test_result(
            test_run_id, image_bytes, f"output.{ext}"
        )

        async with self.session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"prompt-test-result:{test_run_id}"},
            )
            run = await session.get(TestRun, test_run_id)
            if not run:
                return

            existing = await session.scalar(
                select(TestProduct).where(TestProduct.test_run_id == test_run_id)
            )
            if existing is not None:
                run.output_product_id = existing.id
                run.status = "completed"
                return

            # Find or create the default test-results product library
            lib = await session.scalar(
                select(TestProductLibrary).where(
                    TestProductLibrary.library_type == "test_result",
                    TestProductLibrary.name == "测试结果",
                )
            )
            if not lib:
                lib = TestProductLibrary(name="测试结果", description="提示词测试自动生成的结果", library_type="test_result")
                session.add(lib)
                await session.flush()

            version = await session.get(PromptVersion, run.prompt_version_id)
            request_snapshot = dict(run.request_snapshot or {})
            metadata = {
                "promptTemplateId": str(version.template_id) if version else None,
                "promptTemplateName": version.name if version else "",
                "promptVersionId": str(run.prompt_version_id),
                "promptVersionNo": version.version_no if version else None,
                "inputAssetId": str(run.input_asset_id) if run.input_asset_id else None,
                "inputText": run.input_text,
                "generationParams": request_snapshot.get(
                    "generationParams", dict(version.generation_params or {}) if version else {}
                ),
                "model": request_snapshot.get("model", self.model),
                "durationMs": duration_ms,
            }

            # Create product record for the output
            product = TestProduct(
                library_id=lib.id,
                name=f"测试结果-{str(test_run_id)[:8]}",
                product_type="image",
                minio_bucket=bucket,
                minio_key=key,
                file_type=file_type,
                file_size=file_size,
                test_run_id=test_run_id,
                extra_metadata=metadata,
            )
            session.add(product)
            await session.flush()

            run.output_product_id = product.id
            run.status = "completed"
            run.duration_ms = duration_ms

    async def _set_status(
        self,
        test_run_id: UUID,
        status: str,
        *,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Update test run status."""
        async with self.session_factory() as session, session.begin():
            run = await session.get(TestRun, test_run_id)
            if not run:
                return
            run.status = status
            if error_message is not None:
                run.error_message = error_message
            if duration_ms is not None:
                run.duration_ms = duration_ms
