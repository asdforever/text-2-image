from io import BytesIO
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.app.reverse_project_repository import InMemoryReverseProjectRepository
from backend.app.repository import InMemoryRepository


def png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="PNG")
    return output.getvalue()


class Planner:
    def __init__(self, result=None, error: AppError | None = None) -> None:
        self.result = result
        self.error = error
        self.requests = []
        self.observations = {}

    async def plan_modules(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        context = json.loads(request.user_prompt)
        if context.get("analysisStage") == "reference_observation":
            reference_id = context["referenceImageId"]
            return self.observations.get(reference_id, observation_result(reference_id))
        return self.result


def analysis_result(reference_id: str) -> dict:
    return {
        "category": "厨房电器",
        "summary": "围绕快速出餐组织整套详情内容。",
        "suitableFor": "强调效率与易清洁的厨房电器",
        "goal": "建立从痛点到证据再到转化的内容顺序",
        "requiredMaterials": "产品多角度图、容量和材质事实",
        "notSuitableFor": "缺少事实依据的功效或认证表达",
        "overall": {
            "contentFlow": "痛点、核心卖点、证据、场景、收口",
            "visualSystem": "暖白底配深灰信息层级",
            "moduleStrategy": "每屏只回答一个购买问题",
            "adaptationRules": "参数和承诺必须替换为当前商品事实",
        },
        "modules": [
            {
                "id": "benefit-proof",
                "title": "核心卖点证据",
                "referenceImageId": reference_id,
                "goal": "说明快速出餐的依据",
                "layout": "左侧产品，右侧三层信息",
                "informationHierarchy": "结论、证据、补充说明",
                "typography": "大标题配紧凑参数",
                "colorAndLighting": "暖白环境光，产品高光克制",
                "adaptationNotes": "替换为当前商品容量和功率",
            }
        ],
    }


def observation_result(reference_id: str, direction="按键端朝画面左下，尾部朝右上") -> dict:
    return {
        "referenceImageId": reference_id,
        "sceneLayout": "白底，无道具，主体自然落地",
        "productPresentation": {
            "axisAnchors": {
                "front": {"label": "按键端" if "左下" in direction else "前端", "x": 0.2, "y": 0.8 if "左下" in direction else 0.5},
                "rear": {"label": "尾部", "x": 0.8, "y": 0.2 if "左下" in direction else 0.5},
            },
            "subjectCount": 1,
            "visibleSideAnchor": {"label": "近景侧壁", "x": .7, "y": .75},
            "positionAndScale": "主体居中，宽度约占画面八成",
            "viewpoint": "低角度俯视，非顶视",
            "orientation": direction,
            "visibleSurfaces": "顶面与画面右侧侧壁同时可见",
            "partAnchors": "前端由按键分缝与滚轮定位，尾部为饱满外壳",
            "framingAndOcclusion": "主体完整，无前景遮挡",
            "contactAndShadow": "底面接触支撑面，阴影贴合底缘",
            "visualEvidence": "按键分缝落在画面左下，滚轮靠前，侧壁清楚可见",
            "uncertainties": ["无法从单张图精确测量相机俯视角"],
        },
        "adaptationNotes": "以当前商品真实部件为准，保留观察到的机位和朝向，不复制参考商品标识",
    }


@pytest.mark.asyncio
async def test_analysis_isolates_reference_images_and_uses_observed_pose_in_saved_modules():
    planner = Planner()
    vision_planner = Planner()
    app = make_app(planner=planner)
    app.state.reverse_project_service.image_observer = vision_planner
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "逐张观察"})).json()["data"]
        for filename, color in [("misleading-top-view.png", "red"), ("misleading-45-degrees.png", "blue")]:
            project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
                files={"file": (filename, png_bytes(color), "image/png")})).json()["data"]
        first, second = [item["id"] for item in project["references"]]
        planner.result = analysis_result(first)
        second_module = {**planner.result["modules"][0], "id": "second", "referenceImageId": second}
        planner.result["modules"].append(second_module)
        vision_planner.observations = {first: observation_result(first), second: observation_result(second, "前端朝画面左，尾部朝右，长轴水平")}
        response = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": project["revision"]})
        analyzed = response.json()["data"]
        published = (await client.post(f"/api/reverse-projects/{project['id']}/versions", json={"expectedRevision": analyzed["revision"]})).json()["data"]
        business = (await client.post("/api/projects", json={"name": "当前商品"})).json()["data"]
        execution = (await client.post(f"/api/projects/{business['id']}/reverse-execution", json={"versionId": published["id"]})).json()["data"]
        compiled = (await client.post(f"/api/projects/{business['id']}/reverse-execution/compile", json={"expectedRevision": execution["revision"]})).json()["data"]

    assert response.status_code == 200, response.text
    modules = response.json()["data"]["modules"]
    assert "按键端朝画面左下，尾部朝画面右上" in modules[0]["layout"]
    assert "前端朝画面左，尾部朝画面右" in modules[1]["layout"]
    assert "精确测量" in modules[0]["layout"]
    assert "左侧产品，右侧三层信息" not in modules[0]["layout"]
    observations = [r for r in vision_planner.requests if json.loads(r.user_prompt).get("analysisStage") == "reference_observation"]
    assert len(observations) == 2
    assert len(planner.requests) == 1
    assert {json.loads(r.user_prompt)["referenceImageId"]: r.image_inputs for r in observations} == {
        first: [png_bytes("red")], second: [png_bytes("blue")],
    }
    assert all("misleading" not in r.user_prompt for r in observations)
    assert all("misleading" not in r.user_prompt for r in planner.requests)
    assert "按键端朝画面左下，尾部朝画面右上" in compiled["tasks"][0]["promptDraft"]
    assert "前端朝画面左，尾部朝画面右" in compiled["tasks"][1]["promptDraft"]


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_observation", ["wrong_reference", "missing_camera"])
async def test_invalid_reference_observation_keeps_existing_analysis(broken_observation):
    planner = Planner()
    app = make_app(planner=planner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "保留草稿"})).json()["data"]
        project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
            files={"file": ("a.png", png_bytes("red"), "image/png")})).json()["data"]
        reference_id = project["references"][0]["id"]
        project = (await client.patch(f"/api/reverse-projects/{project['id']}", json={"expectedRevision": project["revision"], **editable_document(reference_id)})).json()["data"]
        planner.result = analysis_result(reference_id)
        observation = observation_result(reference_id)
        if broken_observation == "wrong_reference":
            observation["referenceImageId"] = "another-image"
        else:
            del observation["productPresentation"]["viewpoint"]
        planner.observations[reference_id] = observation
        response = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": project["revision"]})
        after = (await client.get(f"/api/reverse-projects/{project['id']}")).json()["data"]
    assert response.status_code == 502
    assert after["revision"] == project["revision"]
    assert after["modules"] == project["modules"]
    assert after["analysis"]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mapping", ["missing", "duplicate"])
async def test_analysis_rejects_incomplete_reference_coverage_before_observing(mapping):
    planner = Planner()
    app = make_app(planner=planner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "图片对应校验"})).json()["data"]
        for color in ["red", "blue"]:
            project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
                files={"file": ("a.png", png_bytes(color), "image/png")})).json()["data"]
        planner.result = analysis_result(project["references"][0]["id"])
        if mapping == "duplicate":
            planner.result["modules"].append({**planner.result["modules"][0], "id": "duplicate-reference"})
        response = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": project["revision"]})
        after = (await client.get(f"/api/reverse-projects/{project['id']}")).json()["data"]
    assert response.status_code == 502
    assert after["revision"] == project["revision"]
    assert after["modules"] == []
    assert all(json.loads(r.user_prompt).get("analysisStage") != "reference_observation" for r in planner.requests)


def editable_document(reference_id: str) -> dict:
    result = analysis_result(reference_id)
    return {
        "category": result["category"],
        "summary": result["summary"],
        "suitableFor": result["suitableFor"],
        "goal": result["goal"],
        "requiredMaterials": result["requiredMaterials"],
        "notSuitableFor": result["notSuitableFor"],
        "overall": result["overall"],
        "modules": result["modules"],
    }


def make_app(*, workspace_id=UUID(int=22), reverse_repository=None, storage=None, planner=None):
    project_repository = InMemoryProjectRepository()
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=11), workspace_id, "owner")
    )
    return create_app(
        settings=Settings(_env_file=None, local_workspace_id=workspace_id),
        repository=InMemoryRepository(),
        project_repository=project_repository,
        project_asset_storage=storage or MemoryProjectAssetStorage(),
        identity_provider=identity,
        reverse_project_repository=reverse_repository or InMemoryReverseProjectRepository(),
        module_planner=planner,
    )


@pytest.mark.asyncio
async def test_analysis_format_error_identifies_the_stage_and_preserves_references():
    app = make_app(planner=Planner(error=AppError("MODULE_PLANNER_INVALID_RESPONSE", "规划大师返回格式无效", 502)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "格式失败"})).json()["data"]
        project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
                    files={"file": ("one.png", png_bytes("green"), "image/png")})).json()["data"]
        failed = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": project["revision"]})
        after = (await client.get(f"/api/reverse-projects/{project['id']}")).json()["data"]
    assert failed.status_code == 502
    assert "整体策略" in failed.json()["error"]["message"]
    assert after["analysis"]["status"] == "failed"
    assert after["analysis"]["error"] == failed.json()["error"]["message"]
    assert after["references"] == project["references"]
    assert after["revision"] == project["revision"]


@pytest.mark.asyncio
async def test_interrupted_analysis_releases_running_state_and_can_be_retried():
    app = make_app(planner=Planner(error=asyncio.CancelledError()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "分析中断"})).json()["data"]
        project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
                    files={"file": ("one.png", png_bytes("green"), "image/png")})).json()["data"]
        with pytest.raises(asyncio.CancelledError):
            await app.state.reverse_project_service.analyze(UUID(project["id"]), project["revision"])
        after = (await client.get(f"/api/reverse-projects/{project['id']}")).json()["data"]
        assert after["analysis"]["status"] == "failed"
        assert after["references"] == project["references"]
        assert after["revision"] == project["revision"]
        app.state.reverse_project_service.planner = Planner(result=analysis_result(project["references"][0]["id"]))
        retried = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": after["revision"]})
        assert retried.status_code == 200
        assert retried.json()["data"]["analysis"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancelling_finished_request_does_not_clear_a_new_analysis_claim():
    committed = asyncio.Event()
    release = asyncio.Event()

    class DelayedCompletion(InMemoryReverseProjectRepository):
        async def complete_analysis(self, *args):
            result = await super().complete_analysis(*args)
            committed.set()
            await release.wait()
            return result

    repository = DelayedCompletion()
    planner = Planner()
    app = make_app(reverse_repository=repository, planner=planner)
    service = app.state.reverse_project_service
    project = await service.create_project("分析归属")
    project = await service.add_reference(project.id, "one.png", "image/png", png_bytes("green"))
    planner.result = analysis_result(str(project.references[0].id))
    previous = asyncio.create_task(service.analyze(project.id, project.revision))
    await committed.wait()
    try:
        next_claim = await repository.claim_analysis(service.workspace_id, project.id, project.revision + 1)
        previous.cancel()
        with pytest.raises(asyncio.CancelledError):
            await previous
        current = await service.get_project(project.id)
        assert current.analysis_status == "running"
        assert current.revision == next_claim.revision
        assert current.summary == analysis_result(str(project.references[0].id))["summary"]
    finally:
        release.set()
        if not previous.done():
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)


@pytest.mark.asyncio
async def test_all_reverse_stages_use_published_prompt_model_instead_of_environment_observer(monkeypatch):
    monkeypatch.setenv("CONTEXT_BASE_URL", "https://legacy.example.test")
    monkeypatch.setenv("CONTEXT_API_KEY", "legacy-test-key")
    monkeypatch.setenv("CONTEXT_MODEL", "qwen3.8-27b")
    legacy = Planner(error=AppError("MODULE_PLANNER_FAILED", "旧模型不应该被调用", 502))
    configured = Planner()
    app = make_app(planner=legacy)

    class PublishedPromptModels:
        async def bind(self, content, planner):
            return SimpleNamespace(compiler=configured)

    app.state.reverse_project_service.prompt_models = PublishedPromptModels()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/reverse-projects", json={"name": "统一提示词模型"})).json()["data"]
        project = (await client.post(f"/api/reverse-projects/{project['id']}/references",
                    files={"file": ("one.png", png_bytes("green"), "image/png")})).json()["data"]
        configured.result = analysis_result(project["references"][0]["id"])
        analyzed = await client.post(f"/api/reverse-projects/{project['id']}/analyze", json={"expectedRevision": project["revision"]})
    assert analyzed.status_code == 200
    assert legacy.requests == []
    assert [json.loads(request.user_prompt)["analysisStage"] for request in configured.requests] == [
        "overall_strategy", "reference_observation",
    ]


@pytest.mark.asyncio
async def test_reverse_project_api_creates_and_lists_full_workspace_projects() -> None:
    app = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/reverse-projects",
            json={"name": "厨房小家电反推", "category": "小家电"},
        )
        listed = await client.get("/api/reverse-projects")

    assert created.status_code == 201, created.text
    project = created.json()["data"]
    assert project["name"] == "厨房小家电反推"
    assert project["category"] == "小家电"
    assert project["revision"] == 1
    assert project["references"] == []
    assert project["overall"] == {
        "contentFlow": "",
        "visualSystem": "",
        "moduleStrategy": "",
        "adaptationRules": "",
    }
    assert project["modules"] == []
    assert project["analysis"] == {"status": "idle"}
    assert project["versions"] == []
    assert project["latestVersionId"] is None
    assert listed.status_code == 200
    assert listed.json()["data"] == [project]


@pytest.mark.asyncio
async def test_reverse_project_updates_use_revision_and_workspace_scope() -> None:
    shared = InMemoryReverseProjectRepository()
    app_a = make_app(workspace_id=UUID(int=22), reverse_repository=shared)
    app_b = make_app(workspace_id=UUID(int=33), reverse_repository=shared)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_a), base_url="http://test"
    ) as client_a:
        created = (await client_a.post("/api/reverse-projects", json={"name": "A"})).json()["data"]
        patched = await client_a.patch(
            f"/api/reverse-projects/{created['id']}",
            json={"expectedRevision": 1, "summary": "人工摘要"},
        )
        stale = await client_a.patch(
            f"/api/reverse-projects/{created['id']}",
            json={"expectedRevision": 1, "summary": "过期写入"},
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_b), base_url="http://test"
    ) as client_b:
        hidden = await client_b.get(f"/api/reverse-projects/{created['id']}")
        listed = await client_b.get("/api/reverse-projects")

    assert patched.status_code == 200
    assert patched.json()["data"]["revision"] == 2
    assert patched.json()["data"]["summary"] == "人工摘要"
    assert stale.status_code == 409
    assert hidden.status_code == 404
    assert listed.json()["data"] == []


@pytest.mark.asyncio
async def test_reference_order_publish_immutability_and_planning_interfaces() -> None:
    app = make_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = (await client.post("/api/reverse-projects", json={"name": "整套反推"})).json()["data"]
        first = await client.post(
            f"/api/reverse-projects/{project['id']}/references",
            files={"file": ("one.png", png_bytes("red"), "image/png")},
        )
        second = await client.post(
            f"/api/reverse-projects/{project['id']}/references",
            files={"file": ("two.png", png_bytes("blue"), "image/png")},
        )
        first_id = first.json()["data"]["references"][0]["id"]
        second_id = second.json()["data"]["references"][1]["id"]
        ordered = await client.put(
            f"/api/reverse-projects/{project['id']}/reference-order",
            json={"expectedRevision": 3, "referenceIds": [second_id, first_id]},
        )
        patched = await client.patch(
            f"/api/reverse-projects/{project['id']}",
            json={"expectedRevision": 4, **editable_document(first_id)},
        )
        published = await client.post(
            f"/api/reverse-projects/{project['id']}/versions",
            json={"expectedRevision": 5},
        )
        replay = await client.post(
            f"/api/reverse-projects/{project['id']}/versions",
            json={"expectedRevision": 5},
        )
        changed = await client.patch(
            f"/api/reverse-projects/{project['id']}",
            json={"expectedRevision": 5, "summary": "发布后的草稿修改"},
        )
        removed = await client.delete(
            f"/api/reverse-projects/{project['id']}/references/{first_id}"
        )
        preview = await client.get(
            f"/api/reverse-projects/{project['id']}/references/{first_id}/preview"
        )
        version_id = published.json()["data"]["id"]
        frozen = await client.get(
            f"/api/reverse-projects/{project['id']}/versions/{version_id}"
        )

    assert first.status_code == second.status_code == 200
    assert [item["id"] for item in ordered.json()["data"]["references"]] == [second_id, first_id]
    assert [item["ordinal"] for item in ordered.json()["data"]["references"]] == [1, 2]
    assert patched.status_code == 200
    assert published.status_code == 201
    assert replay.json()["data"]["id"] == published.json()["data"]["id"]
    assert changed.json()["data"]["summary"] == "发布后的草稿修改"
    assert all(item["id"] != first_id for item in removed.json()["data"]["references"])
    assert preview.status_code == 200
    assert preview.content == png_bytes("red")
    assert frozen.json()["data"]["document"]["summary"] == analysis_result(first_id)["summary"]

    service = app.state.reverse_project_service
    version = await service.get_version(UUID(version_id))
    overall = await service.planning_context(version.id)
    selected = await service.planning_context(version.id, "benefit-proof")
    overall_images = await service.planning_images(version.id)
    module_images = await service.planning_images(version.id, "benefit-proof")
    assert overall["introduction"] == {
        "category": "厨房电器",
        "summary": analysis_result(first_id)["summary"],
        "suitableFor": analysis_result(first_id)["suitableFor"],
        "goal": analysis_result(first_id)["goal"],
        "requiredMaterials": analysis_result(first_id)["requiredMaterials"],
        "notSuitableFor": analysis_result(first_id)["notSuitableFor"],
    }
    assert overall["modules"] == [
        {"id": "benefit-proof", "title": "核心卖点证据", "goal": "说明快速出餐的依据"}
    ]
    assert selected["modules"] == analysis_result(first_id)["modules"]
    assert overall_images == ([], [])
    assert module_images == ([png_bytes("red")], ["image/png"])


@pytest.mark.asyncio
async def test_publish_requires_complete_document() -> None:
    app = make_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = (await client.post("/api/reverse-projects", json={"name": "空草稿"})).json()["data"]
        response = await client.post(
            f"/api/reverse-projects/{project['id']}/versions",
            json={"expectedRevision": 1},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REVERSE_PROJECT_NOT_PUBLISHABLE"


@pytest.mark.asyncio
async def test_analysis_uses_images_and_failure_preserves_manual_draft() -> None:
    success_planner = Planner()
    app = make_app(planner=success_planner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = (await client.post("/api/reverse-projects", json={"name": "AI 反推"})).json()["data"]
        uploaded = await client.post(
            f"/api/reverse-projects/{project['id']}/references",
            files={"file": ("one.png", png_bytes("green"), "image/png")},
        )
        reference_id = uploaded.json()["data"]["references"][0]["id"]
        success_planner.result = analysis_result(reference_id)
        analyzed = await client.post(
            f"/api/reverse-projects/{project['id']}/analyze",
            json={"expectedRevision": 2},
        )

    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["data"]["analysis"] == {"status": "completed"}
    assert analyzed.json()["data"]["revision"] == 3
    assert success_planner.requests[0].image_inputs == [png_bytes("green")]
    assert success_planner.requests[0].image_mime_types == ["image/png"]
    # The downstream image model receives text only for the reference pose.
    # Require the vision request to resolve pose in image coordinates rather
    # than infer it from a filename such as "45 degrees".
    analysis_prompt = success_planner.requests[1].system_prompt
    assert "画面坐标" in analysis_prompt
    assert "前端与后端" in analysis_prompt
    assert "可见面" in analysis_prompt
    assert "占画比例" in analysis_prompt
    assert "文件名" in analysis_prompt
    assert "不要把画面内旋转角当作相机俯视角" in analysis_prompt

    failure_planner = Planner(error=AppError("MODULE_PLANNER_FAILED", "模型请求失败", 502))
    failed_app = make_app(planner=failure_planner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=failed_app), base_url="http://test"
    ) as client:
        failed_project = (await client.post("/api/reverse-projects", json={"name": "失败保留"})).json()["data"]
        uploaded = await client.post(
            f"/api/reverse-projects/{failed_project['id']}/references",
            files={"file": ("one.png", png_bytes("yellow"), "image/png")},
        )
        patched = await client.patch(
            f"/api/reverse-projects/{failed_project['id']}",
            json={"expectedRevision": 2, "summary": "人工编辑不能丢"},
        )
        failure = await client.post(
            f"/api/reverse-projects/{failed_project['id']}/analyze",
            json={"expectedRevision": patched.json()["data"]["revision"]},
        )
        after = await client.get(f"/api/reverse-projects/{failed_project['id']}")

    assert failure.status_code == 502
    assert failure.json()["error"] == {"code": "MODULE_PLANNER_FAILED", "message": "模型请求失败"}
    assert after.json()["data"]["summary"] == "人工编辑不能丢"
    assert after.json()["data"]["analysis"] == {"status": "failed", "error": "模型请求失败"}


@pytest.mark.asyncio
async def test_inflight_analysis_cannot_overwrite_newer_manual_edits() -> None:
    entered = asyncio.Event()
    released = asyncio.Event()

    class BlockingPlanner(Planner):
        async def plan_modules(self, request):
            entered.set()
            await released.wait()
            return await super().plan_modules(request)

    planner = BlockingPlanner()
    app = make_app(planner=planner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = (await client.post("/api/reverse-projects", json={"name": "并发保护"})).json()["data"]
        uploaded = await client.post(
            f"/api/reverse-projects/{project['id']}/references",
            files={"file": ("one.png", png_bytes("orange"), "image/png")},
        )
        reference_id = uploaded.json()["data"]["references"][0]["id"]
        planner.result = analysis_result(reference_id)
        pending = asyncio.create_task(
            client.post(
                f"/api/reverse-projects/{project['id']}/analyze",
                json={"expectedRevision": 2},
            )
        )
        await entered.wait()
        edited = await client.patch(
            f"/api/reverse-projects/{project['id']}",
            json={"expectedRevision": 2, "summary": "分析期间的人工修改"},
        )
        released.set()
        analyzed = await pending
        after = await client.get(f"/api/reverse-projects/{project['id']}")

    assert edited.status_code == 200
    assert analyzed.status_code == 409
    assert after.json()["data"]["summary"] == "分析期间的人工修改"
    assert after.json()["data"]["analysis"]["status"] == "failed"


@pytest.mark.asyncio
async def test_bindings_replace_only_the_same_target_slot() -> None:
    app = make_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        business = (await client.post("/api/projects", json={"name": "业务商品"})).json()["data"]
        reverse = (await client.post("/api/reverse-projects", json={"name": "绑定来源"})).json()["data"]
        uploaded = await client.post(
            f"/api/reverse-projects/{reverse['id']}/references",
            files={"file": ("one.png", png_bytes("purple"), "image/png")},
        )
        reference_id = uploaded.json()["data"]["references"][0]["id"]
        patched = await client.patch(
            f"/api/reverse-projects/{reverse['id']}",
            json={"expectedRevision": 2, **editable_document(reference_id)},
        )
        version = await client.post(
            f"/api/reverse-projects/{reverse['id']}/versions",
            json={"expectedRevision": patched.json()["data"]["revision"]},
        )
        version_id = version.json()["data"]["id"]
        hero = await client.put(
            f"/api/projects/{business['id']}/reverse-bindings",
            json={"target": "hero", "scope": "overall", "versionId": version_id},
        )
        suite = await client.put(
            f"/api/projects/{business['id']}/reverse-bindings",
            json={
                "target": "suite",
                "scope": "module",
                "versionId": version_id,
                "targetModuleId": "task-benefit",
                "sourceModuleId": "benefit-proof",
            },
        )
        replaced = await client.put(
            f"/api/projects/{business['id']}/reverse-bindings",
            json={"target": "hero", "scope": "overall", "versionId": version_id},
        )
        hero_only = await client.get(
            f"/api/projects/{business['id']}/reverse-bindings?target=hero"
        )
        all_reverse = await client.get(
            f"/api/reverse-projects/{reverse['id']}/bindings"
        )
        removed = await client.delete(
            f"/api/projects/{business['id']}/reverse-bindings/{suite.json()['data']['id']}"
        )

    assert hero.status_code == suite.status_code == replaced.status_code == 200
    assert hero_only.json()["data"] == [replaced.json()["data"]]
    assert len(all_reverse.json()["data"]) == 2
    assert {item["target"] for item in all_reverse.json()["data"]} == {"hero", "suite"}
    assert removed.status_code == 200
    assert removed.json()["data"] is True
