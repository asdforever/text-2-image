"""从生成时快照投影画布脉络，不读取当前提示词目录。"""

from typing import Any


def style_harmonization_steps(jobs, assets) -> list[dict[str, Any]]:
    available = {str(asset.id) for asset in assets if asset.state == "available"}
    steps = []
    for job in jobs:
        for task in job["tasks"]:
            if task.get("outputAssetId") not in available:
                continue
            reference = job.get("referenceAsset")
            sources = [task["sourceAssetId"]]
            if reference and reference["assetId"] not in sources:
                sources.append(reference["assetId"])
            steps.append({
                "id": f"style-harmonization:{task['id']}", "kind": "style-harmonization",
                "title": "局部风格统一", "sourceAssetIds": sources,
                "outputAssetIds": [task["outputAssetId"]], "outputVersionIds": [],
                "finalPrompt": job["finalPrompt"], "taskPrompt": job["promptSnapshot"].get("content", ""),
                "constraints": {}, "canRegenerate": False,
                "parameters": {**task["parameters"], "styleMode": job["mode"], "referenceAsset": reference},
            })
    return steps


async def canvas_generation_steps(project_id, workspace_id, assets, batches, edit_tasks) -> list[dict[str, Any]]:
    steps: dict[str, dict[str, Any]] = {}
    available = [asset for asset in assets if asset.state == "available"]
    for asset in available:
        if asset.generation_snapshot_id is None or batches is None:
            continue
        execution = await batches.get_slot_execution(asset.generation_snapshot_id)
        if execution is None:
            continue
        batch, module = execution.batch, execution.module_task
        if batch.workspace_id != workspace_id or batch.project_id != project_id:
            continue
        selection = dict(module.snapshot.get("selection", batch.snapshot.get("selection", {})))
        if "moduleParameters" in module.snapshot:
            selection["moduleParameters"] = module.snapshot["moduleParameters"]
        sources = batch.snapshot.get("sourceAssets") if batch.kind == "suite" else [batch.snapshot.get("sourceAsset", {"assetId": str(batch.source_asset_id)})]
        key = f"batch-module:{module.id}"
        if key not in steps:
            steps[key] = {
                "id": key, "kind": "hero" if selection.get("module", {}).get("mode") == "hero" else batch.kind,
                "batchStatus": batch.status,
                "batchId": str(batch.id),
                "batchCreatedAt": batch.created_at.isoformat(),
                "title": module.snapshot.get("title") or selection.get("module", {}).get("label") or selection.get("module", {}).get("name") or "图片生成",
                "sourceAssetIds": [str(item["assetId"]) for item in (sources or []) if isinstance(item, dict) and item.get("assetId")],
                "outputAssetIds": [], "outputVersionIds": [],
                "finalPrompt": module.final_prompt or "", "taskPrompt": module.confirmed_task_prompt or "",
                "constraints": module.snapshot.get("constraints", batch.snapshot.get("constraints", {})),
                "parameters": selection,
            }
        steps[key]["outputAssetIds"].append(str(asset.id))
    for task in edit_tasks:
        if task.status == "archived":
            continue
        for version in task.versions:
            outputs = [str(a.id) for a in available if a.generation_snapshot_id == version.id or a.source_snapshot.get("imageEditVersionId") == str(version.id) or (len(task.versions) == 1 and a.source_snapshot.get("imageEditTaskId") == str(task.id))]
            config = version.config_snapshot or task.config_snapshot
            parameters = dict(config.get("generationParams", config))
            for field in ("modelConnection", "providerModel"):
                if field in config:
                    parameters[field] = config[field]
            prompt = version.prompt_snapshot or task.prompt_snapshot
            key = f"edit-version:{version.id}"
            source_id = version.source_snapshot.get("assetId") or task.source_snapshot.get("assetId")
            steps[key] = {
                "id": key, "kind": "white" if config.get("outputKind") == "white_background" else "edit",
                "title": "生成白底图" if config.get("outputKind") == "white_background" else "修改图片",
                "sourceAssetIds": [str(source_id)] if source_id else [], "outputAssetIds": outputs,
                "outputVersionIds": [str(version.id)],
                "finalPrompt": prompt.get("finalPrompt", prompt.get("summary", "")), "taskPrompt": "",
                "constraints": {}, "parameters": parameters,
            }
    return list(steps.values())
