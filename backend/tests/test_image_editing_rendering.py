from io import BytesIO

import pytest
from PIL import Image, ImageDraw

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
async def test_add_text_automatically_designs_typography_within_user_region():
    editor = Editor()
    operation = op("add_text", text="新品上市", prompt="暖色手写标题，与背景协调", region={"x": .2, "y": .2, "width": .5, "height": .2, "rotation": 0})
    result, prompt = await execute_operations(png("red"), [operation], editor, ratio="1:1", resolution="标准 1K", connection=None)
    assert "新品上市" in prompt and "暖色手写标题，与背景协调" in prompt
    assert "自动选择字体、字号、颜色和排版" in prompt
    assert "用户明确描述的文字效果优先" in prompt
    assert "textStyle" not in prompt and "fontSize" not in prompt
    assert len(editor.requests) == 1
    image = Image.open(BytesIO(result)).convert("RGB")
    assert image.size == (100, 80)
    assert len(editor.requests[0].ordered_image_inputs()) == 1
    assert Image.open(BytesIO(editor.requests[0].image_bytes)).convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((30, 20)) == (0, 0, 255)


@pytest.mark.asyncio
async def test_text_replacement_passes_exact_strings_region_and_style():
    editor = Editor()
    result, prompt = await execute_operations(png("red"), [op("change_text", originalText="旧标题", newText="新品上市", prompt="保持排版", region={"x": .2, "y": .2, "width": .5, "height": .2, "rotation": 0})], editor, ratio="1:1", resolution="标准 1K", connection=None)
    assert "旧标题" in prompt and "新品上市" in prompt and "保持排版" in prompt
    assert Image.open(BytesIO(result)).size == (100, 80)
    assert len(editor.requests[0].ordered_image_inputs()) == 1


@pytest.mark.parametrize("operation", [
    op("redraw", strokes=[], prompt="修改", feather=0),
    op("crop_resize", region={"x": 0, "y": 0, "width": 1, "height": 1}, width=90000, height=90000),
    op("change_text", originalText="旧", newText="新", region={"x": .9, "y": 0, "width": .5, "height": .5}),
])
def test_invalid_edits_are_rejected_before_provider_call(operation):
    with pytest.raises(AppError): validate_operations([operation])


@pytest.mark.asyncio
async def test_text_edit_does_not_cut_complete_provider_letter_at_region_edge():
    # A complete glyph returned across the layout guide must not become half a glyph.
    source = Image.new("RGB", (100, 80), "white")
    candidate = source.copy()
    ImageDraw.Draw(candidate).rectangle((20, 10, 45, 35), outline="black", width=3)
    data = BytesIO()
    candidate.save(data, format="PNG")

    class LetterEditor:
        async def edit(self, request):
            return ImageEditResult(data.getvalue(), "image/png", {})

    result, _ = await execute_operations(png("white"), [op("add_text", text="口", region={"x": .2, "y": .125, "width": .2, "height": .2})], LetterEditor(), ratio="1:1", resolution="标准 1K", connection=None)
    image = Image.open(BytesIO(result)).convert("RGB")
    assert image.getpixel((44, 34)) == (0, 0, 0), "The completed lower-right strokes were hard-clipped"
    assert image.tobytes() == candidate.tobytes()


@pytest.mark.asyncio
async def test_text_and_brush_edits_keep_full_text_but_limit_brush_changes():
    class MixedEditor:
        def __init__(self): self.requests = []
        async def edit(self, request):
            self.requests.append(request)
            image = Image.open(BytesIO(request.image_bytes)).convert("RGB")
            if len(self.requests) == 1:
                ImageDraw.Draw(image).rectangle((20, 10, 45, 35), outline="black", width=3)
            else:
                # Model drift outside a brush selection must still be discarded.
                image.paste("blue", (0, 0, 100, 80))
            data = BytesIO(); image.save(data, format="PNG")
            return ImageEditResult(data.getvalue(), "image/png", {})

    editor = MixedEditor()
    operations = [op("add_text", text="口", region={"x": .2, "y": .125, "width": .2, "height": .2}), op("erase", strokes=[{"mode": "draw", "width": .1, "points": [{"x": .8, "y": .8}]}])]
    result, _ = await execute_operations(png("white"), operations, editor, ratio="1:1", resolution="标准 1K", connection=None)
    image = Image.open(BytesIO(result)).convert("RGB")
    assert len(editor.requests) == 2
    assert image.getpixel((44, 34)) == (0, 0, 0)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert image.getpixel((80, 64)) == (0, 0, 255)


@pytest.mark.asyncio
async def test_invalid_later_brush_mask_fails_before_text_provider_call():
    editor = Editor()
    stroke = {"width": .2, "points": [{"x": .5, "y": .5}]}
    operations = [op("add_text", text="标题", region={"x": .2, "y": .2, "width": .5, "height": .2}), op("erase", strokes=[{"mode": "draw", **stroke}, {"mode": "erase", **stroke}])]
    with pytest.raises(AppError):
        await execute_operations(png("white"), operations, editor, ratio="1:1", resolution="标准 1K", connection=None)
    assert editor.requests == []


@pytest.mark.asyncio
async def test_prompt_edit_sends_current_image_without_mask_and_can_be_cropped():
    editor = Editor()
    result, prompt = await execute_operations(png("red"), [
        op("prompt_edit", prompt="把背景变成木质桌面，保留商品和文字"),
        op("crop_resize", region={"x": 0, "y": 0, "width": 1, "height": 1}, width=50, height=40),
    ], editor, ratio="4:3", resolution="标准 1K", connection=None)
    assert len(editor.requests) == 1
    request = editor.requests[0]
    assert len(request.ordered_image_inputs()) == 1
    assert Image.open(BytesIO(request.image_bytes)).convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert "木质桌面" in prompt and "保留商品和文字" in prompt
    assert "选区外" not in prompt
    output = Image.open(BytesIO(result)).convert("RGB")
    assert output.size == (50, 40)
    assert output.getpixel((0, 0)) == (0, 0, 255)


@pytest.mark.parametrize("prompt", ["", "   ", None, {}, "x" * 8001])
def test_prompt_edit_rejects_empty_or_invalid_instruction(prompt):
    with pytest.raises(AppError):
        validate_operations([op("prompt_edit", prompt=prompt)])


@pytest.mark.asyncio
async def test_prompt_edit_then_brush_uses_edited_image_and_preserves_outside_mask():
    class SequenceEditor(Editor):
        async def edit(self, request):
            self.requests.append(request)
            return ImageEditResult(png("blue" if len(self.requests) == 1 else "green"), "image/png", {})
    editor = SequenceEditor()
    result, _ = await execute_operations(png("red"), [op("prompt_edit", prompt="更换背景"), op("redraw", strokes=[{"mode": "draw", "width": .2, "points": [{"x": .5, "y": .5}]}], prompt="改成绿色", feather=0)], editor, ratio="4:3", resolution="标准 1K", connection=None)
    assert len(editor.requests) == 2
    assert Image.open(BytesIO(editor.requests[1].image_bytes)).convert("RGB").getpixel((0, 0)) == (0, 0, 255)
    output = Image.open(BytesIO(result)).convert("RGB")
    assert output.getpixel((0, 0)) == (0, 0, 255)
    assert output.getpixel((50, 40)) == (0, 128, 0)
