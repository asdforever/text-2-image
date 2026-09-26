from io import BytesIO

import pytest
from PIL import Image

from backend.app.application.image_editing_rendering import execute_operations, validate_operations
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.core.errors import AppError


def png(color, size=(100, 80)):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


class Editor:
    def __init__(self): self.requests = []
    async def edit(self, request):
        self.requests.append(request)
        return ImageEditResult(png("blue"), "image/png", {})


def op(kind, **payload):
    return {"operationId": kind, "type": kind, "payload": {"schemaVersion": 2, **payload}}


@pytest.mark.asyncio
async def test_crop_resize_is_local_and_has_exact_output_dimensions():
    editor = Editor()
    result, prompt = await execute_operations(png("red"), [op("crop_resize", region={"x": .1, "y": .25, "width": .5, "height": .5}, width=50, height=40)], editor, ratio="1:1", resolution="标准 1K", connection=None)
    image = Image.open(BytesIO(result))
    assert image.size == (50, 40)
    assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert editor.requests == []


@pytest.mark.asyncio
async def test_redraw_uses_real_prompt_and_guide_and_protects_unselected_pixels():
    editor = Editor()
    operations = [op("redraw", strokes=[{"mode": "draw", "width": .2, "points": [{"x": .5, "y": .5}]}], prompt="改成蓝色布料", feather=0)]
    result, prompt = await execute_operations(png("red"), operations, editor, ratio="1:1", resolution="标准 1K", connection=None)
    image = Image.open(BytesIO(result)).convert("RGB")
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((50, 40)) == (0, 0, 255)
    assert "改成蓝色布料" in prompt
    assert len(editor.requests[0].ordered_image_inputs()) == 2


@pytest.mark.asyncio
async def test_text_replacement_passes_exact_strings_region_and_style():
    editor = Editor()
    result, prompt = await execute_operations(png("red"), [op("change_text", originalText="旧标题", newText="新品上市", prompt="保持排版", region={"x": .2, "y": .2, "width": .5, "height": .2, "rotation": 0})], editor, ratio="1:1", resolution="标准 1K", connection=None)
    assert "旧标题" in prompt and "新品上市" in prompt and "保持排版" in prompt
    assert Image.open(BytesIO(result)).convert("RGB").getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize("operation", [
    op("redraw", strokes=[], prompt="修改", feather=0),
    op("crop_resize", region={"x": 0, "y": 0, "width": 1, "height": 1}, width=90000, height=90000),
    op("change_text", originalText="旧", newText="新", region={"x": .9, "y": 0, "width": .5, "height": .5}),
])
def test_invalid_edits_are_rejected_before_provider_call(operation):
    with pytest.raises(AppError): validate_operations([operation])
