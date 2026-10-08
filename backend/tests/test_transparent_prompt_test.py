import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from backend.app.core.errors import AppError
from backend.app.test_executor import TestExecutor as Executor


@pytest.mark.asyncio
@pytest.mark.parametrize("transparent", [True, False])
async def test_marketplace_transparent_test_sends_flag_and_checks_result(monkeypatch, transparent):
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (2, 2, 6, 6))
    out = BytesIO()
    (image if transparent else image.convert("RGB")).save(out, format="PNG")
    captured = {}
    async def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(out.getvalue()).decode()}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    executor = Executor(None, None, api_base_url="https://image.example.test", api_key="test")
    if transparent:
        data, mime = await executor._call_image_api("抠出商品", image_b64="source", generation_params={"background": "transparent"})
        assert mime == "image/png"
        assert Image.open(BytesIO(data)).getchannel("A").getextrema() == (0, 255)
    else:
        with pytest.raises(AppError, match="透明"):
            await executor._call_image_api("抠出商品", image_b64="source", generation_params={"background": "transparent"})
    assert captured["background"] == "transparent"
    assert captured["output_format"] == "png"
