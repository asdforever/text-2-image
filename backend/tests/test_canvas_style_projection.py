from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.test_style_harmonization import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reference", "custom", "prompt"])
async def test_workbench_exposes_saved_style_candidates_with_frozen_prompt_and_exact_inputs(mode):
    service, canvas, project, source, white, old, editor, _ = await fixture()
    payload = {"assetIds": [str(old.id), str(white.id)], "mode": mode}
    if mode == "reference":
        payload["referenceAssetId"] = str(source.id)
    elif mode == "custom":
        payload["prompt"] = "柔和暖光，保留商品与文字"
    else:
        _, version = await service.prompts.create_template_with_version(code="style", name="风格", kind="generation", kind_name="风格", execution_target="image", body="冻结的风格正文", user_prompt_template="")
        payload["promptVersionId"] = str(version.id)
    job = await service.submit(project.id, payload, "canvas-style")
    await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    if mode == "prompt":
        version.body = "后来修改的正文"
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.style_harmonization_service = service
    app.state.canvas_generation_service = canvas
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/suites/{project.id}/workbench")
        assert response.status_code == 200
        data = response.json()["data"]
        steps = [s for s in data["generationSteps"] if s["kind"] == "style-harmonization"]
        assert len(steps) == 2
        for step, task in zip(steps, saved["tasks"]):
            assert step["sourceAssetIds"] == [task["sourceAssetId"]] + ([str(source.id)] if mode == "reference" else [])
            assert step["outputAssetIds"] == [task["outputAssetId"]]
            assert step["finalPrompt"] == saved["finalPrompt"]
            assert step["taskPrompt"] == saved["promptSnapshot"]["content"]
            assert step["parameters"]["providerModel"] == "fake-model"
            assert step["parameters"]["styleMode"] == mode
            assert step["canRegenerate"] is False
        assert data["generationTracks"] == []
        assert len(editor.requests) == 2, "Reading the canvas must not generate again"
        assert await service.assets.get_selections(project.id) == {"generated": old.id}
        await service.assets.delete_asset(project.id, UUID(saved["tasks"][0]["outputAssetId"]))
        remaining = (await client.get(f"/api/suites/{project.id}/workbench")).json()["data"]["generationSteps"]
        assert len([s for s in remaining if s["kind"] == "style-harmonization"]) == 1
