from io import BytesIO

import httpx
import pytest
from PIL import Image

from backend.app.application.hero_generation_ports import ImageEditInput, ImageEditRequest
from backend.app.core.errors import AppError
from backend.app.providers.openai_compatible import OpenAICompatibleImageEditor


@pytest.mark.asyncio
async def test_image_editor_posts_one_source_file_and_fixed_generation_fields() -> None:
    source = _png_bytes((8, 6), (20, 40, 60))
    generated = _png_bytes((6, 8), (100, 120, 140))
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = body
        return httpx.Response(200, json={"data": [{"b64_json": _b64(generated)}]})

    editor = OpenAICompatibleImageEditor(
        base_url="https://image.example.test",
        api_key="image-secret",
        model="gpt-image-2",
        timeout_ms=600000,
        transport=httpx.MockTransport(handler),
    )
    result = await editor.edit(
        ImageEditRequest(
            prompt="固定约束卡与实时任务提示词",
            image_bytes=source,
            image_mime_type="image/png",
            image_filename="source-product.png",
            aspect_ratio="3:4",
            resolution="高清 2K",
        )
    )

    assert result.image_bytes == generated
    assert result.image_mime_type == "image/png"
    assert result.provider_request == {
        "model": "gpt-image-2",
        "endpoint": "/v1/images/edits",
        "size": "1792x2400",
        "quality": "medium",
        "n": 1,
        "responseFormat": "b64_json",
        "sourceImageCount": 1,
    }
    assert captured["url"] == "https://image.example.test/v1/images/edits"
    assert captured["authorization"] == "Bearer image-secret"
    assert str(captured["content_type"]).startswith("multipart/form-data; boundary=")
    body = captured["body"]
    assert isinstance(body, bytes)
    for expected in (
        b'name="model"',
        b"gpt-image-2",
        b'name="image"; filename="source-product.png"',
        b"image/png",
        source,
        b'name="prompt"',
        "固定约束卡与实时任务提示词".encode(),
        b'name="size"',
        b"1792x2400",
        b'name="quality"',
        b"medium",
        b'name="n"',
        b"1",
        b'name="response_format"',
        b"b64_json",
    ):
        assert expected in body
    assert body.count(b'name="image";') == 1


@pytest.mark.asyncio
async def test_image_editor_posts_ordered_multiple_source_files() -> None:
    first = _png_bytes((8, 6), (20, 40, 60))
    second = _png_bytes((6, 8), (60, 40, 20))
    generated = _png_bytes((6, 8), (100, 120, 140))
    captured: dict[str, bytes] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = await request.aread()
        return httpx.Response(200, json={"data": [{"b64_json": _b64(generated)}]})

    editor = _editor(httpx.MockTransport(handler))
    request = ImageEditRequest(
        prompt="生成套图",
        image_bytes=first,
        image_mime_type="image/png",
        image_filename="first.png",
        aspect_ratio="3:4",
        resolution="标准 1K",
        image_inputs=(
            ImageEditInput(first, "image/png", "first.png"),
            ImageEditInput(second, "image/png", "second.png"),
        ),
    )
    result = await editor.edit(request)

    assert result.provider_request["sourceImageCount"] == 2
    assert captured["body"].count(b'name="image";') == 2
    assert captured["body"].find(b"first.png") < captured["body"].find(b"second.png")
    assert first in captured["body"]
    assert second in captured["body"]


@pytest.mark.parametrize(
    ("ratio", "resolution", "expected_size"),
    [
        ("1:1", "标准 1K", "1024x1024"),
        ("1:1", "1K", "1024x1024"),
        ("3:4", "2K", "1792x2400"),
        ("4:3", "高清 2K", "2400x1792"),
        ("16:9", "超清 4K", "5504x3072"),
    ],
)
def test_image_editor_maps_supported_ratio_and_resolution(
    ratio: str, resolution: str, expected_size: str
) -> None:
    assert OpenAICompatibleImageEditor.resolve_parameters(ratio, resolution) == {
        "size": expected_size,
        "quality": "medium",
    }


def test_image_editor_rejects_unknown_size_before_provider_call() -> None:
    with pytest.raises(AppError) as raised:
        OpenAICompatibleImageEditor.resolve_parameters("9:16", "影院 8K")

    assert raised.value.code == "IMAGE_PROVIDER_PARAMETERS_UNSUPPORTED"
    assert raised.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("encoded", ["not-base64!", "YWJj"])
async def test_image_editor_rejects_invalid_provider_image(encoded: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    editor = _editor(httpx.MockTransport(handler))

    with pytest.raises(AppError) as raised:
        await editor.edit(_edit_request())

    assert raised.value.code == "IMAGE_PROVIDER_INVALID_RESPONSE"
    assert raised.value.status_code == 502


@pytest.mark.asyncio
async def test_image_editor_normalizes_timeout_and_http_body_without_secrets() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("image-secret", request=request)
        return httpx.Response(500, json={"error": "image-secret upstream details"})

    editor = _editor(httpx.MockTransport(handler))

    with pytest.raises(AppError) as timeout:
        await editor.edit(_edit_request())
    with pytest.raises(AppError) as failed:
        await editor.edit(_edit_request())

    assert timeout.value.code == "IMAGE_PROVIDER_TIMEOUT"
    assert timeout.value.message == "image provider timed out"
    assert failed.value.code == "IMAGE_PROVIDER_FAILED"
    assert failed.value.message == "image provider request failed"
    assert "image-secret" not in repr(timeout.value)
    assert "image-secret" not in repr(failed.value)


def _editor(transport: httpx.AsyncBaseTransport) -> OpenAICompatibleImageEditor:
    return OpenAICompatibleImageEditor(
        base_url="https://image.example.test",
        api_key="image-secret",
        model="gpt-image-2",
        timeout_ms=1000,
        transport=transport,
    )


def _edit_request() -> ImageEditRequest:
    return ImageEditRequest(
        prompt="生成主图",
        image_bytes=_png_bytes((4, 4), (10, 20, 30)),
        image_mime_type="image/png",
        image_filename="source.png",
        aspect_ratio="1:1",
        resolution="标准 1K",
    )


def _png_bytes(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _b64(value: bytes) -> str:
    import base64

    return base64.b64encode(value).decode("ascii")
