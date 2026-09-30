"""图片编辑操作的验证、指令编译和选区保护；纯裁剪不请求模型。"""
from io import BytesIO
from itertools import groupby
import json
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .hero_generation_ports import ImageEditInput, ImageEditRequest
from ..core.errors import AppError

MAX_PIXELS = 32_000_000
KINDS = {"add_text", "change_text", "redraw", "erase", "crop_resize", "prompt_edit"}


def invalid(message):
    raise AppError("IMAGE_EDIT_INVALID_OPERATION", message, 400)


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        invalid("编辑参数超出允许范围")
    return value


def region_of(payload):
    region = payload.get("region")
    if not isinstance(region, dict): invalid("请框选编辑区域")
    x, y = number(region.get("x"), 0, 1), number(region.get("y"), 0, 1)
    width, height = number(region.get("width"), .0001, 1), number(region.get("height"), .0001, 1)
    if x + width > 1.000001 or y + height > 1.000001: invalid("编辑区域不能超出原图")
    number(region.get("rotation", 0), -360, 360)
    return region


def validate_operations(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 30: invalid("请添加 1–30 项修改")
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("type") not in KINDS: invalid("此草稿包含旧工具，请移除旧操作后重新编辑")
        kind, payload = operation["type"], operation.get("payload")
        if not isinstance(payload, dict): invalid("编辑参数无效")
        if kind in {"add_text", "change_text", "crop_resize"}: region_of(payload)
        if kind in {"add_text", "change_text"}:
            keys = ("text",) if kind == "add_text" else ("originalText", "newText")
            for key in keys:
                if not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 2000: invalid("请填写有效的文字内容（最多 2000 字）")
        if kind == "add_text" and "textStyle" in payload:
            style = payload["textStyle"]
            if not isinstance(style, dict): invalid("文字样式无效")
            number(style.get("fontSize"), 8, 1000)
            number(style.get("strokeWidth", 0), 0, 20)
        if len(str(payload.get("prompt", ""))) > 8000: invalid("编辑要求过长")
        if kind == "prompt_edit" and (not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip()): invalid("请填写修改要求")
        if kind in {"redraw", "erase"}:
            strokes = payload.get("strokes")
            if not isinstance(strokes, list) or not 1 <= len(strokes) <= 500: invalid("请先绘制要修改的选区")
            if kind == "redraw" and not str(payload.get("prompt", "")).strip(): invalid("请填写重绘要求")
            number(payload.get("feather", 0), 0, .4)
            for stroke in strokes:
                if not isinstance(stroke, dict) or stroke.get("mode") not in {"draw", "erase"}: invalid("选区笔画无效")
                number(stroke.get("width"), .00001, 2)
                points = stroke.get("points")
                if not isinstance(points, list) or not 1 <= len(points) <= 20000: invalid("选区笔画点数无效")
                for point in points:
                    if not isinstance(point, dict): invalid("选区坐标无效")
                    number(point.get("x"), 0, 1); number(point.get("y"), 0, 1)
        if kind == "crop_resize":
            width, height = number(payload.get("width"), 1, 30000), number(payload.get("height"), 1, 30000)
            if int(width) != width or int(height) != height or width * height > MAX_PIXELS: invalid("输出尺寸需为整数，且不能超过 3200 万像素")
    if sum(item["type"] == "crop_resize" for item in operations) > 1: invalid("每次编辑只能设置一项裁剪尺寸")


def load_image(data):
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > MAX_PIXELS: invalid("图片不能超过 3200 万像素")
        return ImageOps.exif_transpose(image).convert("RGBA")


def encode(image):
    output = BytesIO(); image.save(output, format="PNG"); return output.getvalue()


def operation_mask(size, operation):
    width, height = size
    payload = operation["payload"]
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    if operation["type"] in {"redraw", "erase"}:
        for stroke in payload["strokes"]:
            points = [(round(p["x"] * (width - 1)), round(p["y"] * (height - 1))) for p in stroke["points"]]
            diameter = max(1, round(stroke["width"] * min(size)))
            radius, color = diameter / 2, 255 if stroke["mode"] == "draw" else 0
            if len(points) > 1: draw.line(points, fill=color, width=diameter, joint="curve")
            for x, y in points: draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
        if mask.getbbox() is None: invalid("当前选区为空，请重新绘制")
        feather = float(payload.get("feather", 0)) * min(size) * .05
        # 羽化仅在原选区内混合，保证选区外像素完全不变。
        if feather: mask = ImageChops.multiply(mask, mask.filter(ImageFilter.GaussianBlur(feather)))
    else:
        region = region_of(payload)
        cx, cy = (region["x"] + region["width"] / 2) * width, (region["y"] + region["height"] / 2) * height
        angle = math.radians(region.get("rotation", 0))
        corners = [(dx * region["width"] * width / 2, dy * region["height"] * height / 2) for dx, dy in [(-1,-1),(1,-1),(1,1),(-1,1)]]
        draw.polygon([(cx + x*math.cos(angle) - y*math.sin(angle), cy + x*math.sin(angle) + y*math.cos(angle)) for x,y in corners], fill=255)
    return mask


async def execute_operations(source, operations, editor, *, ratio, resolution, connection):
    validate_operations(operations)
    image = load_image(source)
    edits = [item for item in operations if item["type"] != "crop_resize"]
    # Reject empty brush selections before any earlier text generation can incur cost.
    for operation in edits:
        if operation["type"] in {"redraw", "erase"}:
            operation_mask(image.size, operation)
    prompts = []
    # Text regions guide layout, while brush masks define an exact compositing boundary.
    # Keep consecutive edits together without clipping text to a brush/rectangle mask.
    for edit_mode, group in groupby(edits, key=lambda item: "prompt" if item["type"] == "prompt_edit" else "text" if item["type"] in {"add_text", "change_text"} else "masked"):
        is_text = edit_mode == "text"
        mask = Image.new("L", image.size)
        instructions = []
        labels = {"add_text": "添加指定文字", "change_text": "替换指定文字，保留原字体感觉、透视和光影", "redraw": "局部重绘", "erase": "移除选中内容并自然补全背景", "prompt_edit": "按用户要求修改当前图片"}
        for operation in group:
            if edit_mode == "masked":
                mask = ImageChops.lighter(mask, operation_mask(image.size, operation))
            payload = {key: value for key, value in operation["payload"].items() if key not in {"schemaVersion", "strokes"}}
            instruction = labels[operation["type"]] + "：" + json.dumps(payload, ensure_ascii=False)
            if is_text:
                r = region_of(payload)
                bounds = [round(r["x"]*image.width), round(r["y"]*image.height), round((r["x"]+r["width"])*image.width), round((r["y"]+r["height"])*image.height)]
                instruction += "。原图像素位置 [左, 上, 右, 下]：" + json.dumps(bounds)
                instruction += f"；距左 {r['x']:.1%}，距顶 {r['y']:.1%}，文字总宽不超过画面 {r['width']:.1%}，总高不超过画面 {r['height']:.1%}。"
            if operation["type"] == "add_text" and "textStyle" not in payload:
                instruction += "。在指定区域内参考原图风格自动选择字体、字号、颜色和排版，保证文字完整、清晰且自然融入画面；用户明确描述的文字效果优先。"
            instructions.append(instruction)
        source_png = encode(image)
        inputs = (ImageEditInput(source_png, "image/png", "原图.png"),)
        if edit_mode == "prompt":
            guidance = (
                f"这是用户选中的待修改图片，尺寸为 {image.width} × {image.height} 像素。以这张图片为编辑基础，输出完整画幅并保持原图比例。"
                "按照用户的修改要求调整画面，例如替换背景、桌面、场景或光线。"
                "未明确要求修改的商品外形、包装、标识、文字和其他内容应尽量保留；不要把编辑要求画成图片上的文字，也不要添加选区或辅助标记。修改要求：\n"
            )
        elif is_text:
            guidance = (
                f"这是待编辑原图，尺寸为 {image.width} × {image.height} 像素。输出完整画幅，保持原图比例。"
                "region 为相对原图左上角的归一化位置，表示文字排版范围，所有笔画必须完整落在此范围内，不得越界。"
                "文字必须逐字完整呈现；根据区域大小合理缩小字号或换行，四周留出空白，禁止截字、缺字或把文字压在画面边缘。"
                "不要绘制选区框、色块底板或辅助标记，除非用户明确要求。"
                "保留原图商品、包装、原有文字（包括底部文案）、背景、光影和构图；禁止放大商品、移动主体、改变留白或重新设计整张图，仅执行指定文字修改。只执行以下修改：\n"
            )
        else:
            guide = Image.composite(Image.new("RGBA", image.size, "#ff4444"), image, mask.point(lambda v: round(v * .45)))
            inputs += (ImageEditInput(encode(guide), "image/png", "选区指引.png"),)
            guidance = "第一张是原图，第二张是选区指引，红色仅标记允许修改的区域，不是输出内容。保持完整画幅、商品结构、选区外文字与构图不变，不改变画面比例。只执行以下修改：\n"
        prompt = guidance + "\n".join(instructions)
        prompts.append(prompt)
        request = ImageEditRequest(prompt=prompt, image_bytes=source_png, image_mime_type="image/png", image_filename="原图.png", aspect_ratio=ratio, resolution=resolution,
            image_inputs=inputs, model_connection=connection)
        result = await editor.edit(request)
        candidate = load_image(result.image_bytes).resize(image.size, Image.Resampling.LANCZOS)
        image = candidate if edit_mode != "masked" else Image.composite(candidate, image, mask)
    prompt = "\n\n".join(prompts) if prompts else "本地裁剪与尺寸调整"
    for operation in operations:
        if operation["type"] != "crop_resize": continue
        payload, width, height = operation["payload"], image.width, image.height
        r = region_of(payload)
        left, top = round(r["x"]*width), round(r["y"]*height)
        right, bottom = min(width, max(left+1, round((r["x"]+r["width"])*width))), min(height, max(top+1, round((r["y"]+r["height"])*height)))
        image = image.crop((left, top, right, bottom)).resize((int(payload["width"]), int(payload["height"])), Image.Resampling.LANCZOS)
    return encode(image), prompt
