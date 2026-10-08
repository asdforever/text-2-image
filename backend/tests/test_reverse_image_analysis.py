import pytest
from pydantic import ValidationError
from PIL import Image
from io import BytesIO
import json
from pathlib import Path
from copy import deepcopy

from backend.app.application.reverse_image_analysis import ReferenceImageObservation, observed_layout
from backend.tests.test_reverse_projects import observation_result
from backend.app.application import reverse_image_analysis as analysis


@pytest.mark.asyncio
async def test_detail_review_keeps_whole_reference_context_so_cable_end_is_not_reversed():
    captured = json.loads((Path(__file__).parent / "fixtures/reverse-cropped-front-conflict.json").read_text(encoding="utf-8"))
    picture = BytesIO()
    Image.new("RGB", (790, 1387), "black").save(picture, "PNG")
    original = picture.getvalue()
    reference_id = captured["initial"]["referenceImageId"]

    class Observer:
        async def plan_modules(self, request):
            stage = json.loads(request.user_prompt)["analysisStage"]
            if stage == "reference_observation":
                return deepcopy(captured["initial"])
            # The captured crop lost the cable/body context and called the
            # upper slot the front. With the full image it can locate the cable.
            if request.image_inputs[0] != original:
                return deepcopy(captured["cropped"])
            pose = captured["initial"]["productPresentation"]
            return {key: deepcopy(pose[key]) for key in (
                "axisAnchors", "visibleSideAnchor", "viewpoint", "visibleSurfaces",
                "partAnchors", "visualEvidence", "uncertainties"
            )} | {"referenceImageId": reference_id}

    observed = await analysis.observe_reference_image(Observer(), reference_id, original, "image/png")
    assert observed.productPresentation.axisAnchors.front.y == pytest.approx(.78)
    assert observed.productPresentation.axisAnchors.rear.y == pytest.approx(.47)
    assert "前端（线缆出口端）朝画面左下" in observed_layout(observed)
    assert "近距仰视" not in observed_layout(observed)


def test_detail_review_rejects_front_endpoint_at_opposite_end_from_functional_evidence():
    captured = json.loads((Path(__file__).parent / "fixtures/reverse-cropped-front-conflict.json").read_text(encoding="utf-8"))
    bad = deepcopy(captured["cropped"])
    bad["functionalFrontAnchor"] = {"label": "有线鼠标出线口", "x": .5, "y": .84}
    with pytest.raises(ValidationError, match="功能前端"):
        analysis.ProductDetailObservation.model_validate(bad)


def test_detail_review_accepts_front_endpoint_supported_by_cable_exit():
    pose = observation_result("reference")["productPresentation"]
    raw = {key: deepcopy(pose[key]) for key in (
        "axisAnchors", "visibleSideAnchor", "viewpoint", "visibleSurfaces",
        "partAnchors", "visualEvidence", "uncertainties"
    )} | {"referenceImageId": "reference", "functionalFrontAnchor": {
        "label": "出线口", "x": .21, "y": .79
    }}
    observed = analysis.ProductDetailObservation.model_validate(raw)
    assert observed.functionalFrontAnchor.label == "出线口"


@pytest.mark.asyncio
async def test_projected_size_uses_image_dimensions_instead_of_model_claim_about_flat_body():
    picture = BytesIO()
    Image.new("RGB", (800, 1400), "black").save(picture, "PNG")

    class Observer:
        async def plan_modules(self, request):
            if json.loads(request.user_prompt)["analysisStage"] == "reference_observation":
                return observation_result("reference")
            pose = observation_result("reference")["productPresentation"]
            return {key: deepcopy(pose[key]) for key in (
                "axisAnchors", "visibleSideAnchor", "viewpoint", "visibleSurfaces",
                "partAnchors", "visualEvidence", "uncertainties"
            )} | {"referenceImageId": "reference",
                  "bodyBounds": {"left": .1, "top": .48, "right": .9, "bottom": .79},
                  "positionAndScale": "壳体属宽扁形态，高度为宽度的四成"}

    observed = await analysis.observe_reference_image(Observer(), "reference", picture.getvalue(), "image/png")
    layout = observed_layout(observed)
    assert "宽度约占画面80.0%，高度约占画面31.0%" in layout
    assert "投影高宽比约0.678" in layout  # 434px / 640px
    assert "宽扁形态" not in layout
    assert "四成" not in layout


@pytest.mark.asyncio
async def test_review_without_long_axis_preserves_visible_label_and_opening_orientation():
    picture = BytesIO()
    Image.new("RGB", (200, 200), "white").save(picture, "PNG")
    raw = observation_result("bottle")
    raw["productPresentation"]["axisAnchors"] = None
    raw["productPresentation"]["orientation"] = "瓶口朝上，标签面朝向观看者"

    class Observer:
        async def plan_modules(self, request):
            if json.loads(request.user_prompt)["analysisStage"] == "reference_observation":
                return deepcopy(raw)
            pose = raw["productPresentation"]
            return {key: deepcopy(pose[key]) for key in (
                "axisAnchors", "visibleSideAnchor", "viewpoint", "visibleSurfaces",
                "partAnchors", "visualEvidence", "uncertainties"
            )} | {"referenceImageId": "bottle"}

    observed = await analysis.observe_reference_image(Observer(), "bottle", picture.getvalue(), "image/png")
    assert "瓶口朝上，标签面朝向观看者" in observed_layout(observed)
    assert "外轮廓端点估计坐标" not in observed_layout(observed)


@pytest.mark.asyncio
async def test_scene_detail_review_returns_original_coordinates_without_mapping_them_twice():
    picture = BytesIO()
    Image.new("RGB", (320, 240), "white").save(picture, "PNG")
    class Observer:
        def __init__(self):
            self.requests = []
        async def plan_modules(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                raw = observation_result("reference")
                raw["productPresentation"]["axisAnchors"] = {
                    "front": {"label": "前端", "x": .4, "y": .75},
                    "rear": {"label": "尾端", "x": .65, "y": .4},
                }
                return raw
            return {
                "referenceImageId": "reference",
                "axisAnchors": {"front": {"label": "按键轮廓交点", "x": .278125, "y": .8208333333}, "rear": {"label": "尾端", "x": .771875, "y": .3291666667}},
                "visibleSideAnchor": {"label": "近景侧壁中心", "x": .6484375, "y": .7225},
                "viewpoint": "侧前方斜上方",
                "visibleSurfaces": "顶面与画面右侧侧壁",
                "partAnchors": "按键分缝与外轮廓交点作为前端",
                "visualEvidence": "局部可见完整按键分缝与尾端轮廓",
                "uncertainties": [],
            }
    observer = Observer()
    observed = await analysis.observe_reference_image(observer, "reference", picture.getvalue(), "image/png")
    assert len(observer.requests) == 2
    assert observer.requests[1].image_inputs[0] == picture.getvalue()
    assert observer.requests[1].image_inputs[1] != picture.getvalue()
    assert observed.productPresentation.axisAnchors.front.x == pytest.approx(.278125)
    assert observed.productPresentation.axisAnchors.front.y == pytest.approx(.8208333333)
    assert observed.productPresentation.axisAnchors.rear.x == pytest.approx(.771875)
    assert observed.productPresentation.axisAnchors.rear.y == pytest.approx(.3291666667)
    assert observed.productPresentation.visibleSideAnchor.x == pytest.approx(.6484375)
    assert observed.productPresentation.visibleSideAnchor.y == pytest.approx(.7225)
    assert "可见侧壁定位：近景侧壁中心位于原图(0.648, 0.723)" in observed_layout(observed)
    assert "按键轮廓交点朝画面左下" in observed_layout(observed)
    assert observed.productPresentation.viewpoint == "侧前方斜上方"


def test_layout_derives_axis_from_contour_endpoints_instead_of_wheel_position():
    raw = observation_result("reference")
    raw["productPresentation"]["orientation"] = "前端左上，后端右下（滚轮位于主体左上）"
    raw["productPresentation"]["axisAnchors"] = {
        "front": {"label": "按键分缝与外轮廓交点", "x": 0.40, "y": 0.71},
        "rear": {"label": "尾端外轮廓", "x": 0.69, "y": 0.62},
    }
    layout = observed_layout(ReferenceImageObservation.model_validate(raw))
    assert "按键分缝与外轮廓交点朝画面左下" in layout
    assert "尾端外轮廓朝画面右上" in layout
    assert "前端左上" not in layout


@pytest.mark.parametrize("front,rear,expected", [
    ((0.1, 0.5), (0.8, 0.5), "朝画面左"),
    ((0.7, 0.2), (0.3, 0.8), "朝画面右上"),
    ((0.5, 0.9), (0.5, 0.1), "朝画面下"),
    ((0.1, 0.5), (0.8, 0.521), "朝画面左"),
])
def test_axis_direction_uses_top_left_origin_and_downward_y(front, rear, expected):
    raw = observation_result("reference")
    raw["productPresentation"]["axisAnchors"] = {
        "front": {"label": "前端", "x": front[0], "y": front[1]},
        "rear": {"label": "后端", "x": rear[0], "y": rear[1]},
    }
    assert f"前端{expected}，" in observed_layout(ReferenceImageObservation.model_validate(raw))


def test_direction_does_not_change_when_same_product_axis_is_smaller_in_frame():
    for front, rear in [((.3, .5), (.7, .52)), ((.4, .5), (.5, .505))]:
        raw = observation_result("reference")
        raw["productPresentation"]["axisAnchors"] = {
            "front": {"label": "前端", "x": front[0], "y": front[1]},
            "rear": {"label": "尾端", "x": rear[0], "y": rear[1]},
        }
        assert "前端朝画面左上，" in observed_layout(ReferenceImageObservation.model_validate(raw))


@pytest.mark.parametrize("x,y", [(-0.1, 0.5), (0.81, 0.21), (0.77, 0.2)])
def test_unusable_endpoints_are_rejected_instead_of_inventing_a_direction(x, y):
    raw = observation_result("reference")
    raw["productPresentation"]["axisAnchors"]["front"].update(x=x, y=y)
    with pytest.raises(ValidationError):
        ReferenceImageObservation.model_validate(raw)


def test_no_reliable_axis_preserves_explicit_uncertainty():
    raw = observation_result("reference")
    raw["productPresentation"]["axisAnchors"] = None
    raw["productPresentation"]["orientation"] = "无法可靠确定前后端，标签面朝向观看者"
    raw["productPresentation"]["uncertainties"] = ["圆形容器没有可识别前后端"]
    layout = observed_layout(ReferenceImageObservation.model_validate(raw))
    assert "无法可靠确定前后端" in layout
    assert "圆形容器没有可识别前后端" in layout
    assert "外轮廓端点估计坐标" not in layout


def test_occluded_product_allows_omitted_nullable_anchors_without_inventing_pose():
    raw = observation_result("occluded-reference")
    del raw["productPresentation"]["axisAnchors"]
    del raw["productPresentation"]["visibleSideAnchor"]
    raw["productPresentation"]["orientation"] = "鼠标被手掌遮挡，无法可靠定位前后端"
    raw["productPresentation"]["uncertainties"] = ["功能端点和侧壁均不可见"]
    observation = ReferenceImageObservation.model_validate(raw)
    assert observation.productPresentation.axisAnchors is None
    assert observation.productPresentation.visibleSideAnchor is None
    layout = observed_layout(observation)
    assert "鼠标被手掌遮挡" in layout
    assert "外轮廓端点估计坐标" not in layout
    assert "功能端点和侧壁均不可见" in layout
