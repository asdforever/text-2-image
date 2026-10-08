"""Observe one reference image before turning its geometry into reusable text."""

import json
from io import BytesIO
from math import ceil, floor

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..core.errors import AppError
from .module_planning_service import ModuleMasterRequest
from .reference_content_policy import REFERENCE_ANALYSIS_POLICY, clean_reference_text


class ImageAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ProductAxisAnchors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    front: ImageAnchor
    rear: ImageAnchor

    @model_validator(mode="after")
    def distinct_endpoints(self):
        if round(max(abs(self.front.x - self.rear.x), abs(self.front.y - self.rear.y)), 6) <= 0.03:
            raise ValueError("前后端点无法形成可靠长轴，应返回null并说明不确定")
        return self


class ProductBodyBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def nonempty_body(self):
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("产品壳体范围必须具有正宽度和高度")
        return self


class ProductPresentationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    axisAnchors: ProductAxisAnchors | None = None
    visibleSideAnchor: ImageAnchor | None = None
    functionalFrontAnchor: ImageAnchor | None = None
    bodyBounds: ProductBodyBounds | None = None
    subjectCount: StrictInt = Field(ge=0)
    positionAndScale: str = Field(min_length=1, max_length=800)
    viewpoint: str = Field(min_length=1, max_length=800)
    orientation: str = Field(min_length=1, max_length=800)
    visibleSurfaces: str = Field(min_length=1, max_length=800)
    partAnchors: str = Field(min_length=1, max_length=800)
    framingAndOcclusion: str = Field(min_length=1, max_length=800)
    contactAndShadow: str = Field(min_length=1, max_length=800)
    visualEvidence: str = Field(min_length=1, max_length=800)
    uncertainties: list[str] = Field(max_length=10)


class ReferenceImageObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    referenceImageId: str = Field(min_length=1, max_length=100)
    sceneLayout: str = Field(min_length=1, max_length=1000)
    productPresentation: ProductPresentationObservation
    adaptationNotes: str = Field(min_length=1, max_length=5000)


class ProductDetailObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    referenceImageId: str = Field(min_length=1, max_length=100)
    axisAnchors: ProductAxisAnchors | None = None
    visibleSideAnchor: ImageAnchor | None = None
    functionalFrontAnchor: ImageAnchor | None = None
    bodyBounds: ProductBodyBounds | None = None
    positionAndScale: str | None = Field(default=None, min_length=1, max_length=800)
    framingAndOcclusion: str | None = Field(default=None, min_length=1, max_length=800)
    contactAndShadow: str | None = Field(default=None, min_length=1, max_length=800)
    orientation: str | None = Field(default=None, min_length=1, max_length=800)
    viewpoint: str = Field(min_length=1, max_length=800)
    visibleSurfaces: str = Field(min_length=1, max_length=800)
    partAnchors: str = Field(min_length=1, max_length=800)
    visualEvidence: str = Field(min_length=1, max_length=800)
    uncertainties: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def front_agrees_with_functional_evidence(self):
        if self.axisAnchors is not None and self.functionalFrontAnchor is not None:
            evidence = self.functionalFrontAnchor
            front, rear = self.axisAnchors.front, self.axisAnchors.rear
            front_distance = (front.x - evidence.x) ** 2 + (front.y - evidence.y) ** 2
            rear_distance = (rear.x - evidence.x) ** 2 + (rear.y - evidence.y) ** 2
            if front_distance >= rear_distance:
                raise ValueError("功能前端证据与前后端定位冲突，不能把出线口等前端部件安排在尾端")
        return self


def _product_detail(image: bytes, anchors: ProductAxisAnchors):
    with Image.open(BytesIO(image)) as original:
        if min(original.size) < 64:
            return None
        span = max(abs(anchors.front.x - anchors.rear.x), abs(anchors.front.y - anchors.rear.y)) * 1.4
        center_x = (anchors.front.x + anchors.rear.x) / 2
        center_y = (anchors.front.y + anchors.rear.y) / 2
        left = max(0, floor((center_x - span / 2) * original.width))
        top = max(0, floor((center_y - span / 2) * original.height))
        right = min(original.width, ceil((center_x + span / 2) * original.width))
        bottom = min(original.height, ceil((center_y + span / 2) * original.height))
        if (right - left) / original.width > .9 and (bottom - top) / original.height > .9:
            return None
        detail = original.crop((left, top, right, bottom)).convert("RGB")
        scale = 1024 / max(detail.size)
        detail = detail.resize((round(detail.width * scale), round(detail.height * scale)), Image.Resampling.LANCZOS)
        output = BytesIO()
        detail.save(output, "PNG")
        return output.getvalue(), (left / original.width, top / original.height,
                                    right / original.width, bottom / original.height)


async def _refine_product_pose(planner, reference_id: str, image: bytes, mime: str, pose: ProductPresentationObservation):
    if pose.subjectCount != 1:
        return pose
    with Image.open(BytesIO(image)) as original:
        if min(original.size) < 64:
            return pose
        image_width, image_height = original.size
    detail = _product_detail(image, pose.axisAnchors) if pose.axisAnchors is not None else None
    # A crop derived from tentative endpoints can omit the true end of the
    # product. The original remains the coordinate system and source of truth.
    images, mimes = [image], [mime]
    crop_bounds = None
    if detail is not None:
        detail_image, crop_bounds = detail
        images.append(detail_image)
        mimes.append("image/png")
    request = ModuleMasterRequest(
        system_prompt=(
            "你是商品结构与摄影机位复核员。图1是唯一完整参考图，图2（如有）仅为图1的局部放大。"
            + REFERENCE_ANALYSIS_POLICY +
            "先在完整图识别商品和真实部件关系，再用局部图查看细节；裁图可能截掉壳体或使商品难以识别，"
            "不得把裁图边缘当作壳体端点，不得只凭局部开孔或发光条猜商品类别及前后端。"
            "所有坐标都归一化到图1完整原图0..1，绝不能返回局部图坐标；左上原点，x向右、y向下；label使用中文部件名称。"
            "front是功能前端与外轮廓的交点，rear是沿壳体真实长轴的另一端轮廓点；"
            "不要用边界框最左/最右点、滚轮中心、标识中心代替前后端。"
            "鼠标以前端两主键分缝与外轮廓的交点定位front，rear取相反的尾端轮廓；不是单纯取最左点和最右点。"
            "有线鼠标优先以壳体上的真实出线口确认功能前端，沿壳体长轴找相反尾端；"
            "滚轮、主键分缝和出线口的相对关系必须一致，不能把出线口解释成尾部接口，也不能把滚轮横纹当成一排独立按键。"
            "functionalFrontAnchor记录支持前端判断的可见功能部件（如有线鼠标出线口或主键前端），"
            "该点应靠近front而非rear；不可见或无法确认时返回null，不根据常识补出不可见部件。"
            "visibleSideAnchor定位实际可见近景侧壁中央的一点；没有可见侧壁时返回null。"
            "visibleSurfaces只写实际可见面，侧壁称为近景侧壁或远侧侧壁，不用左侧壁/右侧壁，避免混淆商品自身左右和画面左右。"
            "viewpoint也不用左侧/右侧命名，以侧前方、斜上方、平视等机位关系描述。"
            "文字字段不得写坐标，坐标只在axisAnchors、functionalFrontAnchor和visibleSideAnchor中，均使用图1原图坐标。"
            "viewpoint描述顶面/侧壁的展开比例、底缘与立体厚度，无法测准的高度不编造数值。"
            "前端朝画面下不代表仰视，顶面与滚轮可见时按实际可见面的展开关系判断；不猜低机位来解释裁图。"
            "positionAndScale、framingAndOcclusion、contactAndShadow也按完整图复核：产品壳体占比和线缆延伸范围分开，"
            "不能把灯光、线缆、影子算进壳体，不能把局部裁切说成原图裁切。"
            "bodyBounds用图1归一化坐标记录完整可见产品壳体的包围范围（left、top、right、bottom），"
            "不包含线缆、光晕、影子及背景；单一壳体无法可靠定位时返回null。"
            "壳体在画面中的投影高宽比由系统按原图尺寸计算，不在文字中猜比例；"
            "透视缩短不代表真实壳体变宽变扁，不把画面投影轮廓描述成商品自身真实长宽比例。"
            "视觉证据只记部件与轮廓位置，方向由系统计算；不确定的长轴返回null并说明。"
            "orientation记录可观察到的朝向。即使不能定位长轴端点，仍记录瓶口朝上、标签面朝向观看者等可见关系，"
            "无长轴不等于所有朝向未知；不要编造前后端。"
            "严格返回outputSchema对应JSON，不增加字段。"
        ),
        user_prompt=json.dumps({
            "analysisStage": "product_detail_observation", "referenceImageId": reference_id,
            "imageRoles": [{"imageIndex": 1, "role": "full_reference", "coordinateSpace": "original"}]
                + ([{"imageIndex": 2, "role": "detail", "boundsInOriginal": crop_bounds}] if detail else []),
            "outputSchema": ProductDetailObservation.model_json_schema(),
        }, ensure_ascii=False),
        image_inputs=images, image_mime_types=mimes,
    )
    refined = ProductDetailObservation.model_validate(await planner.plan_modules(request))
    if refined.referenceImageId != reference_id:
        raise AppError("REVERSE_ANALYSIS_INVALID_RESPONSE", "产品局部观察返回了错误的参考图对应关系", 502)
    updates = refined.model_dump(exclude={"referenceImageId"})
    for field in ("positionAndScale", "framingAndOcclusion", "contactAndShadow", "orientation"):
        if updates[field] is None:
            del updates[field]
    if refined.bodyBounds is not None:
        bounds = refined.bodyBounds
        width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
        projected_ratio = height * image_height / (width * image_width)
        updates["positionAndScale"] = (
            f"单一壳体中心位于原图({(bounds.left + bounds.right) / 2:.3f}, "
            f"{(bounds.top + bounds.bottom) / 2:.3f})；"
            f"壳体宽度约占画面{width:.1%}，高度约占画面{height:.1%}；"
            f"原图像素中的投影高宽比约{projected_ratio:.3f}。"
            "这是当前机位下的画面投影，不是商品真实长宽比例；商品壳体真实比例以商品输入图为准。"
            "壳体范围不含线缆、光晕、阴影及背景。"
        )
    if refined.axisAnchors is None and refined.orientation is None and pose.axisAnchors is not None:
        updates["orientation"] = "复核无法可靠定位前后端，不能确定长轴方向"
    # The full-context review supersedes tentative pose evidence, including
    # uncertainties caused solely by the crop or the initial classification.
    return ProductPresentationObservation.model_validate({**pose.model_dump(), **updates})


async def observe_reference_image(planner, reference_id: str, image: bytes, mime: str) -> ReferenceImageObservation:
    """An isolated image prevents pose descriptions from drifting between references."""
    request = ModuleMasterRequest(
        system_prompt=(
            "你是商品摄影图像观察员。仅观察本次唯一输入的参考图，先记录视觉证据，再描述产品呈现；"
            + REFERENCE_ANALYSIS_POLICY +
            "这是视觉测读，不是新图设计，不要套用通用主图、45度摄影等模板，不推断文件名或其他图片。"
            "逐项填写 productPresentation：主体数量；相对画面的中心位置和占画比例；"
            "viewpoint区分平视、低角度俯视、高角度俯视、顶视及可见顶面/侧面比例；"
            "不要仅因顶面面积大就判为高角度俯视；先观察侧壁厚度、前端底缘和顶面展开程度，"
            "机位无法可靠分级时写侧前方斜上方等可观察关系，并把精确高度列为不确定，不强行分类。"
            "orientation以观看者画面坐标描述前端与后端、长轴分别朝上/下/左/右或组合方向，"
            "先填写axisAnchors定位前后两端外轮廓的端点：x、y归一化到0..1，左上角为(0,0)，x向右增大，y向下增大。"
            "front必须是功能前端的外轮廓端点，rear是相反的尾端外轮廓端点，不使用滚轮、标签等内部部件的中心替代端点。"
            "label使用中文部件名称，如按键端、尾端，不返回mouse_front等英文代号。"
            "以鼠标为例，前端取两主键分缝与前端外轮廓的交点，沿整个壳体长轴找另一端尾部轮廓点；"
            "滚轮在前半部，但滚轮偏左上不意味着前端整体朝左上，必须观察分缝通向外轮廓哪一端。"
            "系统将由端点坐标计算方向。没有可识别长轴或前后端时axisAnchors返回null并在uncertainties说明，不能编造点位。"
            "partAnchors说明用哪个可见部件判定前后，不能只写左前方、朝向观者或45度；"
            "对无明确前后的物品，使用标签面、开口等锚点，无产品时明确各项不适用；"
            "visibleSideAnchor定位实际可见近景侧壁中央的一点，坐标归一化到原图；没有可见侧壁时返回null。"
            "visibleSurfaces记录实际可见面，侧壁称为近景侧壁或远侧侧壁，不用左侧壁/右侧壁，避免混淆商品自身左右和画面左右；"
            "viewpoint也不用左侧/右侧命名，以侧前方、斜上方、平视等关系描述，不臆测不可见侧。"
            "文字字段不得写坐标，坐标只在axisAnchors和visibleSideAnchor中，由系统整理。"
            "framingAndOcclusion记录裁切、完整展示和遮挡，contactAndShadow记录支撑面与阴影；"
            "visualEvidence必须给出图中部件及轮廓的可见位置，解释机位与朝向的判断依据。"
            "证据只记部件与轮廓的位置，不重复猜测左右朝向，方向以axisAnchors计算结果为准。"
            "不要把画面内旋转角当作相机俯视角，不能从单图测准的角度不要编造精确数值，"
            "不确定之处必须写入uncertainties，没有不确定项时返回空列表。"
            "sceneLayout只描述背景、道具、空间层次，不重复或改写产品姿态。"
            "adaptationNotes说明替换商品后如何遵循这些观察，并保留新商品真实形状和部件，"
            "同类商品的对应功能端必须遵循观察到的画面朝向，不能以适配为由改变机位、长轴或可见面；"
            "adaptationNotes不要重复写具体左右方向，直接要求遵循上述端点定位和产品呈现，以免形成第二套冲突方向。"
            "不复制参考商品的颜色、品牌、纹样、接口或宣称。不得提出与观察相反的机位或朝向。"
            "严格返回outputSchema对应的JSON，不输出未定义字段。"
        ),
        user_prompt=json.dumps({
            "analysisStage": "reference_observation",
            "referenceImageId": reference_id,
            "imageRoles": [{"imageIndex": 1, "referenceImageId": reference_id}],
            "outputSchema": ReferenceImageObservation.model_json_schema(),
        }, ensure_ascii=False),
        image_inputs=[image],
        image_mime_types=[mime],
    )
    observation = ReferenceImageObservation.model_validate(await planner.plan_modules(request))
    if observation.referenceImageId != reference_id:
        raise AppError("REVERSE_ANALYSIS_INVALID_RESPONSE", "逐图观察返回了错误的参考图对应关系", 502)
    observation.productPresentation = await _refine_product_pose(planner, reference_id, image, mime, observation.productPresentation)
    # Camera and direction have one source. Reusing preliminary adaptation text
    # can contradict the final reviewed geometry even when anchors are correct.
    observation.adaptationNotes = (
        "替换商品时遵循上述复核后的主体数量、占画比例、机位、功能前端与尾端定位、可见面及接触关系。"
        "当前商品各部件与壳体的相对位置、连接关系及真实比例以商品输入图为准，"
        "通过重新摆放商品改变朝向，不通过拉伸壳体、移动滚轮、主键或出线口来模仿构图。"
        "不复制参考商品的品牌、颜色、纹样、接口或未经确认的功能；文字与背景不得遮挡关键部件。"
    )
    return observation


def _axis_orientation(pose: ProductPresentationObservation) -> str:
    anchors = pose.axisAnchors
    if anchors is None:
        return pose.orientation
    dx = round(anchors.front.x - anchors.rear.x, 6)
    dy = round(anchors.front.y - anchors.rear.y, 6)
    major = max(abs(dx), abs(dy))

    def direction(x: float, y: float) -> str:
        # Ignore negligible tilt relative to the axis, rather than relative to
        # the whole frame, so a smaller scene product keeps the same direction.
        x_relative, y_relative = round(x / major, 6), round(y / major, 6)
        horizontal = "左" if x_relative < -0.03 else "右" if x_relative > 0.03 else ""
        vertical = "上" if y_relative < -0.03 else "下" if y_relative > 0.03 else ""
        return horizontal + vertical

    front_direction, rear_direction = direction(dx, dy), direction(-dx, -dy)
    return (
        f"{anchors.front.label}朝画面{front_direction}，{anchors.rear.label}朝画面{rear_direction}；"
        f"长轴由{front_direction}指向{rear_direction}。"
        f"外轮廓端点估计坐标：前端({anchors.front.x:.3f}, {anchors.front.y:.3f})，"
        f"后端({anchors.rear.x:.3f}, {anchors.rear.y:.3f})，左上为原点、y向下。"
    )


def observed_layout(observation: ReferenceImageObservation) -> str:
    pose = observation.productPresentation
    side = pose.visibleSideAnchor
    side_location = (
        f"{side.label}位于原图({side.x:.3f}, {side.y:.3f})，左上为原点、y向下"
        if side is not None else "未可靠定位可见侧壁"
    )
    return clean_reference_text("\n".join([
        f"场景与空间：{observation.sceneLayout}",
        f"主体数量：{pose.subjectCount}；位置与占画比例：{pose.positionAndScale}",
        f"相机机位：{pose.viewpoint}",
        f"产品朝向与长轴：{_axis_orientation(pose)}",
        f"前后端/部件锚点：{pose.partAnchors}",
        *([f"功能前端证据：{pose.functionalFrontAnchor.label}位于原图"
           f"({pose.functionalFrontAnchor.x:.3f}, {pose.functionalFrontAnchor.y:.3f})，必须与功能前端同侧"]
          if pose.functionalFrontAnchor is not None else []),
        f"可见面：{pose.visibleSurfaces}",
        f"可见侧壁定位：{side_location}",
        f"裁切与遮挡：{pose.framingAndOcclusion}",
        f"接触与投影：{pose.contactAndShadow}",
        f"观察依据：{pose.visualEvidence}",
        f"不确定项：{'；'.join(pose.uncertainties) or '无'}",
    ]))
