import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from hashlib import sha256
from time import perf_counter
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from .hero_generation_ports import ImageEditInput, ImageEditRequest

logger = logging.getLogger(__name__)


class BatchGenerationWorker:
    def __init__(
        self,
        *,
        repository: Any,
        project_repository: Any,
        project_storage: Any,
        project_asset_service: Any,
        image_editor: Any,
        worker_id: str,
        project_output_archive: Any | None = None,
        lease_seconds: int = 60,
        concurrency: int = 1,
        provider_timeout_seconds: float = 600,
    ) -> None:
        self.repository = repository
        self.project_repository = project_repository
        self.project_storage = project_storage
        self.project_asset_service = project_asset_service
        self.image_editor = image_editor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.concurrency = max(1, concurrency)
        self.project_output_archive = project_output_archive
        self.provider_timeout_seconds = provider_timeout_seconds

    async def run_once(self, *, limit: int, raise_on_error: bool = False,
                       refill: bool = False, poll_interval: float = 1.0) -> int:
        if refill:
            return await self._run_refilling(limit=limit, poll_interval=poll_interval)
        slots = await self.repository.claim_queued_slots(
            self.worker_id,
            limit=limit,
            lease_duration=timedelta(seconds=self.lease_seconds),
        )
        semaphore = asyncio.Semaphore(self.concurrency)
        errors: list[Exception] = []

        async def run(slot) -> bool:
            async with semaphore:
                try:
                    return await self._execute_with_lease(slot.id, slot.lease_token)
                except Exception as exc:
                    errors.append(exc)
                    # 等待所有同批领取的槽位结束，避免下一轮越过并发上限。
                    # 保留当前状态交给租约恢复：未发送可重排，已发送需人工重试。
                    logger.warning("生图槽位 %s 执行异常 (%s)，等待租约恢复", slot.id, type(exc).__name__)
                    return False

        outcomes = await asyncio.gather(*(run(slot) for slot in slots))
        if raise_on_error and errors:
            raise errors[0]
        return sum(outcomes)

    async def _execute_with_lease(self, slot_id, lease_token) -> bool:
        async def renew():
            while True:
                await asyncio.sleep(max(0.05, self.lease_seconds / 3))
                try:
                    renewed = await self.repository.renew_slot_lease(
                        slot_id, lease_token, lease_duration=timedelta(seconds=self.lease_seconds)
                    )
                    if not renewed:
                        return
                except Exception as exc:
                    logger.warning("生图槽位 %s 租约续期失败 (%s)", slot_id, type(exc).__name__)

        heartbeat = asyncio.create_task(renew())
        try:
            return await self._execute_slot(slot_id, lease_token)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _run_refilling(self, *, limit: int, poll_interval: float) -> int:
        if limit < 1:
            return 0
        active: set[asyncio.Task] = set()
        completed = 0
        next_recovery = 0.0

        async def execute(slot):
            try:
                return await self._execute_with_lease(slot.id, slot.lease_token)
            except Exception as exc:
                logger.warning("生图槽位 %s 执行异常 (%s)，等待租约恢复", slot.id, type(exc).__name__)
                return False

        try:
            while True:
                if perf_counter() >= next_recovery:
                    try:
                        await self.repository.recover_expired_leases()
                    except Exception:
                        if not active:
                            raise
                        logger.warning("生图租约恢复暂不可用，保留正在执行的请求")
                    next_recovery = perf_counter() + max(0.1, min(5.0, self.lease_seconds / 3))
                capacity = self.concurrency - len(active)
                if capacity > 0:
                    try:
                        slots = await self.repository.claim_queued_slots(
                            self.worker_id, limit=min(limit, capacity),
                            lease_duration=timedelta(seconds=self.lease_seconds),
                        )
                    except Exception:
                        if not active:
                            raise
                        # Keep already dispatched work alive during a transient queue outage.
                        logger.warning("生图队列读取失败，保留正在执行的请求")
                        slots = []
                    active.update(asyncio.create_task(execute(slot)) for slot in slots)
                if not active:
                    return completed
                done, pending = await asyncio.wait(
                    active, timeout=max(0.1, poll_interval),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                active = pending
                completed += sum(task.result() for task in done)
        finally:
            # Shutdown never leaves untracked provider calls running in this process.
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    async def _execute_slot(self, slot_id, lease_token) -> bool:
        started = perf_counter()
        timings: dict[str, float] = {}
        outcome = "interrupted"
        try:
            result = await self._execute_slot_timed(slot_id, lease_token, timings, started)
            outcome = "succeeded" if result else "failed_or_cancelled"
            return result
        finally:
            logger.info(
                "generation_timing slot=%s outcome=%s total_s=%.3f prepare_s=%s provider_s=%s persist_s=%s",
                slot_id, outcome, perf_counter() - started,
                timings.get("prepare"), timings.get("provider"), timings.get("persist"),
            )

    async def _execute_slot_timed(self, slot_id, lease_token, timings, started) -> bool:
        execution = await self.repository.get_slot_execution(slot_id)
        if execution is None or execution.slot.status != "leased":
            return False
        source_snapshots = _source_asset_snapshots(execution)
        if not source_snapshots:
            return await self._fail_after_dispatch(
                slot_id, lease_token, "BATCH_GENERATION_SNAPSHOT_INVALID", "源图快照无效"
            )
        image_inputs: list[ImageEditInput] = []
        source_hashes: list[str] = []
        for source_snapshot in source_snapshots:
            try:
                asset_id = UUID(str(source_snapshot["assetId"]))
            except (KeyError, TypeError, ValueError):
                return await self._fail_after_dispatch(
                    slot_id, lease_token, "BATCH_GENERATION_SNAPSHOT_INVALID", "源图快照无效"
                )
            asset = await self.project_repository.get_asset(
                asset_id, execution.batch.workspace_id
            )
            source_object = (
                await self.project_repository.get_object(
                    asset.object_id, execution.batch.workspace_id
                )
                if asset is not None
                else None
            )
            if (
                asset is None
                or asset.project_id != execution.batch.project_id
                or asset.state != "available"
                or source_object is None
                or source_object.state != "available"
            ):
                return await self._fail_after_dispatch(
                    slot_id, lease_token, "INVALID_SOURCE_ASSET", "源图不可用"
                )
            stored = await self.project_storage.get(source_object.storage_key)
            actual_hash = sha256(stored.data).hexdigest() if stored is not None else ""
            expected_hash = str(source_snapshot.get("sha256", source_object.sha256))
            if (
                stored is None
                or stored.content_type != source_object.media_type
                or str(source_snapshot.get("objectId", source_object.id)) != str(source_object.id)
                or str(source_snapshot.get("mediaType", source_object.media_type))
                != source_object.media_type
                or expected_hash != source_object.sha256
                or actual_hash != expected_hash
            ):
                return await self._fail_after_dispatch(
                    slot_id, lease_token, "INVALID_SOURCE_ASSET", "源图对象或哈希与确认快照不一致"
                )
            image_inputs.append(
                ImageEditInput(
                    stored.data,
                    source_object.media_type,
                    source_object.original_filename,
                )
            )
            source_hashes.append(expected_hash)
        if len(image_inputs) > 1 and not bool(
            getattr(self.image_editor, "supports_multiple_source_images", False)
        ):
            return await self._fail_after_dispatch(
                slot_id,
                lease_token,
                "IMAGE_PROVIDER_MULTI_SOURCE_UNSUPPORTED",
                "当前图片 Provider 不支持多张源图",
            )
        selection = execution.module_task.snapshot.get("selection")
        if not isinstance(selection, dict):
            selection = execution.batch.snapshot.get("selection", {})
        final_prompt = execution.module_task.final_prompt
        if not isinstance(final_prompt, str) or not final_prompt.strip():
            return await self._fail_after_dispatch(
                slot_id, lease_token, "BATCH_GENERATION_SNAPSHOT_INVALID", "批次提示词快照无效"
            )
        request = ImageEditRequest(
            prompt=final_prompt,
            image_bytes=image_inputs[0].image_bytes,
            image_mime_type=image_inputs[0].image_mime_type,
            image_filename=image_inputs[0].image_filename,
            aspect_ratio=str(selection.get("aspectRatio", "")),
            resolution=str(selection.get("resolution", "")),
            image_inputs=tuple(image_inputs),
            model_connection=selection.get("modelConnection"),
        )
        try:
            described = self.image_editor.describe_request(request)
            if isinstance(described, dict):
                described = {**described, "sourceImageSha256s": source_hashes}
            request_summary = _safe_request_summary(described)
            await self.repository.mark_dispatching(
                slot_id,
                lease_token,
                provider_request_summary=request_summary,
            )
            timings["prepare"] = round(perf_counter() - started, 3)
            provider_started = perf_counter()
            try:
                async with asyncio.timeout(self.provider_timeout_seconds):
                    generated = await self.image_editor.edit(request)
            finally:
                timings["provider"] = round(perf_counter() - provider_started, 3)
        except TimeoutError:
            try:
                if await self.repository.is_slot_cancel_requested(slot_id, lease_token):
                    await self.repository.complete_cancelled_slot(slot_id, lease_token)
                    return False
                await self.repository.mark_needs_retry(
                    slot_id, lease_token, "PROVIDER_DISPATCH_UNKNOWN",
                    "生图请求超时，结果不确定，请检查服务商记录后手动重试",
                )
            except AppError:
                pass
            return False
        except AppError as exc:
            return await self._fail_after_dispatch(slot_id, lease_token, exc.code, exc.message)
        except Exception:
            return await self._fail_after_dispatch(
                slot_id, lease_token, "IMAGE_PROVIDER_FAILED", "图片 Provider 请求失败"
            )
        if await self.repository.is_slot_cancel_requested(slot_id, lease_token):
            await self.repository.complete_cancelled_slot(slot_id, lease_token)
            return False
        # Once output exists, finish its short persistence phase during graceful
        # shutdown. Cancelling an upload after it committed can orphan the asset.
        persistence = asyncio.create_task(self._persist_output(
            execution, slot_id, lease_token, generated, final_prompt, selection, timings
        ))
        try:
            return await asyncio.shield(persistence)
        except asyncio.CancelledError:
            await persistence
            raise

    async def _persist_output(self, execution, slot_id, lease_token, generated,
                              final_prompt, selection, timings) -> bool:
        created_asset = None
        persist_started = perf_counter()
        try:
            created_asset = await self.project_asset_service.create_generated_asset(
                execution.batch.project_id,
                generated.image_bytes,
                generated.image_mime_type,
                f"batch-{execution.batch.id}-{execution.slot.id}.png",
                source_asset_id=execution.batch.source_asset_id,
                generation_snapshot_id=execution.slot.id,
            )
            if self.project_output_archive is not None:
                project = await self.project_repository.get_project(
                    execution.batch.project_id, execution.batch.workspace_id
                )
                module = execution.module_task.snapshot.get("selection", {}).get("module", {})
                product_type = "hero" if module.get("mode") == "hero" else "detail"
                await self.project_output_archive.archive_project_output(
                    project_id=execution.batch.project_id,
                    project_name=project.name if project is not None else "项目成品",
                    product_type=product_type,
                    source_version_id=created_asset.id,
                    preview_url=f"/api/projects/{execution.batch.project_id}/assets/{created_asset.id}/preview",
                    source_snapshot={"assetId": str(created_asset.id), "batchId": str(execution.batch.id), "slotId": str(execution.slot.id)},
                    prompt_snapshot={"finalPrompt": final_prompt},
                    config_snapshot=dict(selection),
                )
            if await self.repository.is_slot_cancel_requested(slot_id, lease_token):
                await self._compensate(execution.batch.project_id, created_asset)
                await self.repository.complete_cancelled_slot(slot_id, lease_token)
                return False
            await self.repository.complete_slot(slot_id, lease_token, created_asset.id)
            return True
        except AppError as exc:
            await self._compensate(execution.batch.project_id, created_asset)
            return await self._fail_after_dispatch(slot_id, lease_token, exc.code, exc.message)
        except Exception:
            await self._compensate(execution.batch.project_id, created_asset)
            return await self._fail_after_dispatch(
                slot_id, lease_token, "BATCH_GENERATION_PERSIST_FAILED", "生成图片保存失败"
            )
        finally:
            timings["persist"] = round(perf_counter() - persist_started, 3)

    async def _fail_after_dispatch(self, slot_id, lease_token, code: str, message: str) -> bool:
        execution = await self.repository.get_slot_execution(slot_id)
        if execution is not None and execution.slot.status == "leased":
            await self.repository.mark_dispatching(slot_id, lease_token, provider_request_summary={})
        try:
            await self.repository.fail_slot(slot_id, lease_token, code, message)
        except AppError:
            return False
        return False

    async def _compensate(self, project_id, asset: Any | None) -> None:
        if asset is None:
            return
        try:
            await self.project_asset_service.delete_asset(project_id, asset.id)
        except Exception:
            pass


def _safe_request_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked = {"prompt", "image", "image_bytes", "authorization", "api_key", "token"}
    return {
        str(key): item
        for key, item in value.items()
        if str(key).casefold() not in blocked
        and (
            isinstance(item, (str, int, float, bool, type(None)))
            or (isinstance(item, list) and all(isinstance(entry, str) for entry in item))
        )
    }


def _source_asset_snapshots(execution: Any) -> list[dict[str, Any]]:
    if execution.batch.kind == "suite":
        values = execution.batch.snapshot.get("sourceAssets")
        if isinstance(values, list) and values and all(isinstance(item, dict) for item in values):
            return values
        return []
    value = execution.batch.snapshot.get("sourceAsset")
    if isinstance(value, dict):
        return [value]
    return [{"assetId": str(execution.batch.source_asset_id)}]
