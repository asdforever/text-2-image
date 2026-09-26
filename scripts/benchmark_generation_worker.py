"""Explicit, paid smoke test of frozen suite prompts; business data is read-only.

python -m scripts.benchmark_generation_worker --batch-id UUID --output-dir PATH --real
"""
import argparse
import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from backend.app.application.batch_generation_worker import BatchGenerationWorker
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.batch_generation_repository import ConfirmedGenerationModuleInput, InMemoryBatchGenerationRepository
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.storage import MemoryObjectStorage


async def run(batch_id: UUID, output_dir: Path, count: int, concurrency: int):
    app = create_app()
    context = app.state.identity_provider.get_context()
    detail = await app.state.batch_generation_repository.get_batch_detail(batch_id, context.workspace_id)
    if detail is None or detail.batch.kind != "suite":
        raise ValueError("Select an existing confirmed suite batch")
    modules = detail.module_tasks[:count]
    if len(modules) != count or any(not module.final_prompt for module in modules):
        raise ValueError("Not enough frozen module prompts")
    project = await app.state.project_repository.get_project(detail.batch.project_id, context.workspace_id)
    state = {"projects": {project.id: deepcopy(project)}, "assets": {}, "objects": {}}
    storage = MemoryObjectStorage()
    for source in detail.batch.snapshot["sourceAssets"]:
        asset = await app.state.project_repository.get_asset(UUID(source["assetId"]), context.workspace_id)
        obj = await app.state.project_repository.get_object(asset.object_id, context.workspace_id)
        stored = await app.state.project_asset_storage.get(obj.storage_key)
        if stored is None:
            raise ValueError("Source image unavailable")
        state["assets"][asset.id] = deepcopy(asset)
        state["objects"][obj.id] = deepcopy(obj)
        await storage.put(stored)
    projects = InMemoryProjectRepository(state)
    batches = InMemoryBatchGenerationRepository()
    frozen = [
        ConfirmedGenerationModuleInput(
            module.module_key, module.position, 1, deepcopy(module.snapshot),
            module.compiled_task_prompt or "", deepcopy(module.compiler_output or {}),
            module.confirmed_task_prompt or "", module.final_prompt, module.final_prompt_sha256,
        )
        for module in modules
    ]
    batch, _ = await batches.create_confirmed_from_plan(
        context.workspace_id, project.id, uuid4(), detail.batch.source_asset_id,
        str(uuid4()), "benchmark", deepcopy(detail.batch.snapshot), frozen,
    )
    provider = app.state.hero_generation_service.image_editor
    started = perf_counter()
    calls = []

    class MeasuredEditor:
        supports_multiple_source_images = True
        active = 0
        peak = 0

        def describe_request(self, request):
            return provider.describe_request(request)

        async def edit(self, request):
            call = {"index": len(calls) + 1, "started_s": round(perf_counter() - started, 3)}
            calls.append(call)
            self.active += 1
            self.peak = max(self.peak, self.active)
            print(json.dumps({"event": "provider_started", **call, "active": self.active}), flush=True)
            try:
                result = await provider.edit(request)
                call["status"] = "succeeded"
                return result
            except Exception as exc:
                call["status"] = "failed"
                call["error_code"] = getattr(exc, "code", type(exc).__name__)
                raise
            finally:
                self.active -= 1
                call["finished_s"] = round(perf_counter() - started, 3)
                call["duration_s"] = round(call["finished_s"] - call["started_s"], 3)
                print(json.dumps({"event": "provider_finished", **call}), flush=True)

    editor = MeasuredEditor()
    worker = BatchGenerationWorker(
        repository=batches, project_repository=projects, project_storage=storage,
        project_asset_service=ProjectAssetService(projects, storage, app.state.identity_provider),
        image_editor=editor, worker_id="isolated-benchmark", concurrency=concurrency,
    )
    await worker.run_once(limit=count, refill=True)
    result = await batches.get_batch_detail(batch.id, context.workspace_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for slot in result.slots:
        if slot.generated_asset_id:
            asset = await projects.get_asset(slot.generated_asset_id, context.workspace_id)
            obj = await projects.get_object(asset.object_id, context.workspace_id)
            stored = await storage.get(obj.storage_key)
            path = output_dir / f"image-{len(images) + 1}.png"
            path.write_bytes(stored.data)
            images.append(str(path.resolve()))
    report = {
        "source_batch_id": str(batch_id), "count": count, "concurrency": concurrency,
        "peak_provider_calls": editor.peak, "elapsed_s": round(perf_counter() - started, 3),
        "succeeded": result.progress.succeeded, "failed": result.progress.failed,
        "calls": calls, "images": images, "business_data_modified": False,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return result.progress.succeeded == count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", type=UUID, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--real", action="store_true", help="Explicitly authorize paid provider calls")
    args = parser.parse_args()
    if not args.real:
        parser.error("--real is required; this calls the configured image model and may incur charges")
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raise SystemExit(0 if asyncio.run(run(args.batch_id, args.output_dir, args.count, args.concurrency)) else 1)
