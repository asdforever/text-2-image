import base64
import binascii
from copy import copy
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIResponseValidationError, APIStatusError, APITimeoutError

from ..application.hero_generation_ports import (
    ImageEditRequest,
    ImageEditResult,
    PromptCompileRequest,
)
from ..application.module_planning_service import ModuleMasterRequest
from ..application.module_planning_v2 import parse_v2_result
from ..core.errors import AppError
from ..core.image_dimensions import normalize_resolution
from ..image_processing import inspect_image
from .planning_agent import planning_engine_snapshot, run_planning_agent


_IMAGE_SIZE_MAP = {
    "标准 1K": {
        "1:1": "1024x1024",
        "3:4": "896x1200",
        "4:3": "1200x896",
        "16:9": "1376x768",
    },
    "高清 2K": {
        "1:1": "2048x2048",
        "3:4": "1792x2400",
        "4:3": "2400x1792",
        "16:9": "2752x1536",
    },
    "超清 4K": {
        "1:1": "4096x4096",
        "3:4": "3584x4800",
        "4:3": "4800x3584",
        "16:9": "5504x3072",
    },
}
_MAX_PROVIDER_IMAGE_BYTES = 64 * 1024 * 1024


def chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not urlsplit(base).path:
        base += "/v1"
    return f"{base}/chat/completions"


def _chat_provider_error(prefix: str, status_code: int) -> AppError:
    if status_code in {401, 403}:
        return AppError(f"{prefix}_UNAUTHORIZED", "提示词模型认证失败，请检查模型连接的 API Key", 502)
    if status_code == 402:
        return AppError(f"{prefix}_QUOTA_EXHAUSTED", "提示词模型额度不足或账户受限", 502)
    if status_code == 429:
        return AppError(f"{prefix}_QUOTA_EXHAUSTED", "提示词模型额度不足或请求被限流", 502)
    if status_code in {400, 422}:
        return AppError(f"{prefix}_INVALID_REQUEST", "提示词模型拒绝了当前图片输入或请求格式", 502)
    return AppError(f"{prefix}_FAILED", "提示词模型请求失败", 502)


class OpenAIChatProvider:
    def with_connection(self, connection):
        """Create task-local provider state, preserving transport and timeout."""
        bound = copy(self)
        bound._base_url = connection.base_url
        bound._api_key = connection.api_key
        bound._model = connection.model_name
        return bound


class OpenAICompatiblePromptCompiler(OpenAIChatProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout_ms: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout_ms = timeout_ms
        self._transport = transport

    async def compile(self, request: PromptCompileRequest) -> Any:
        if not self._base_url or not self._api_key or not self._model:
            raise AppError(
                "PROMPT_COMPILER_UNAVAILABLE",
                "prompt compiler is not configured",
                503,
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": request.user_prompt}]
        for image in request.ordered_image_inputs():
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:{};base64,{}".format(
                            image.image_mime_type,
                            base64.b64encode(image.image_bytes).decode("ascii"),
                        )
                    },
                }
            )
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {
                    "role": "user",
                    "content": content,
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = httpx.Timeout(self._timeout_ms / 1000)

        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(
                    chat_endpoint(self._base_url),
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException:
            raise AppError(
                "PROMPT_COMPILER_TIMEOUT",
                "prompt compiler timed out",
                504,
            ) from None
        except httpx.RequestError:
            raise AppError(
                "PROMPT_COMPILER_FAILED",
                "prompt compiler request failed",
                502,
            ) from None

        if response.is_error:
            raise _chat_provider_error("PROMPT_COMPILER", response.status_code)

        return _parse_v2_compile_response(response, "PROMPT_COMPILER_INVALID_RESPONSE")


class OpenAICompatibleSuitePlannerCompiler(OpenAIChatProvider):
    """调用兼容 Chat Completions 的多模态模型编译单个详情页模块。"""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout_ms: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout_ms = timeout_ms
        self._transport = transport

    async def compile(self, request: Any) -> dict[str, Any]:
        if not self._base_url or not self._api_key or not self._model:
            raise AppError("PLANNING_COMPILER_UNAVAILABLE", "详情页规划编译服务未配置", 503)
        if not request.image_inputs or len(request.image_inputs) != len(request.image_mime_types):
            raise AppError("PLANNING_COMPILER_INVALID_INPUT", "详情页规划源图输入无效", 400)
        content: list[dict[str, Any]] = [{"type": "text", "text": request.user_prompt}]
        for image_bytes, mime_type in zip(request.image_inputs, request.image_mime_types):
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:{};base64,{}".format(
                            mime_type, base64.b64encode(image_bytes).decode("ascii")
                        )
                    },
                }
            )
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": content},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_ms / 1000), transport=self._transport
            ) as client:
                response = await client.post(
                    chat_endpoint(self._base_url),
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise AppError("PLANNING_COMPILER_TIMEOUT", "详情页规划编译服务超时", 504) from None
        except httpx.RequestError:
            raise AppError("PLANNING_COMPILER_FAILED", "详情页规划编译服务请求失败", 502) from None
        if response.is_error:
            raise _chat_provider_error("PLANNING_COMPILER", response.status_code)
        return _parse_v2_compile_response(response, "PLANNING_COMPILER_INVALID_RESPONSE")

class OpenAICompatibleModulePlanner(OpenAIChatProvider):
    """LangChain 规划大师，保留兼容模型连接与业务输出契约。"""

    def __init__(self, *, base_url: str | None, api_key: str | None, model: str | None,
                 timeout_ms: int, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url, self._api_key, self._model = base_url, api_key, model
        self._timeout_ms, self._transport = timeout_ms, transport

    def with_connection(self, connection):
        bound = copy(self)
        bound._base_url, bound._api_key, bound._model = connection.base_url, connection.api_key, connection.model_name
        return bound

    def engine_snapshot(self) -> dict[str, Any]:
        return planning_engine_snapshot()

    async def plan_modules(self, request: ModuleMasterRequest) -> dict[str, Any]:
        if not self._base_url or not self._api_key or not self._model:
            raise AppError("MODULE_PLANNER_UNAVAILABLE", "规划大师服务未配置", 503)
        if not request.image_inputs or len(request.image_inputs) != len(request.image_mime_types):
            raise AppError("MODULE_PLANNER_INVALID_INPUT", "规划大师源图输入无效", 400)
        content: list[dict[str, Any]] = [{"type": "text", "text": request.user_prompt}]
        for data, mime in zip(request.image_inputs, request.image_mime_types):
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}})
        try:
            result = await run_planning_agent(
                base_url=chat_endpoint(self._base_url).removesuffix("/chat/completions"),
                api_key=self._api_key, model=self._model, timeout_ms=self._timeout_ms,
                system_prompt=request.system_prompt, content=content, transport=self._transport,
            )
        except (APITimeoutError, httpx.TimeoutException):
            raise AppError("MODULE_PLANNER_TIMEOUT", "规划大师服务超时", 504) from None
        except (APIConnectionError, httpx.RequestError):
            raise AppError("MODULE_PLANNER_FAILED", "规划大师请求失败", 502) from None
        except APIStatusError as exc:
            raise _chat_provider_error("MODULE_PLANNER", exc.status_code) from None
        except (APIResponseValidationError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            raise AppError("MODULE_PLANNER_INVALID_RESPONSE", "规划大师返回格式无效", 502) from None
        try:
            payload = _decode_json_message_content(result)
            if not isinstance(payload, dict):
                raise TypeError("planner payload must be an object")
            return payload
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise AppError("MODULE_PLANNER_INVALID_RESPONSE", "规划大师返回格式无效", 502) from None


def _decode_json_message_content(value: Any) -> Any:
    """Decode JSON content and tolerate OpenAI-compatible text envelopes.

    Some compatible gateways return a JSON string containing ``{"type":"text",
    "content":"<json>"}`` instead of returning the planner object directly.
    The envelope is transport metadata, not the planner schema, so unwrap it once.
    """
    if isinstance(value, list):
        text_parts = [
            item.get("text")
            for item in value
            if isinstance(item, dict)
            and item.get("type") in {"text", "output_text"}
            and isinstance(item.get("text"), str)
        ]
        if not text_parts:
            raise TypeError("planner content parts must contain text")
        value = "\n".join(text_parts)

    if isinstance(value, str):
        text = value.strip()
        text = re.sub(r"^<think>.*?</think>\s*", "", text, count=1, flags=re.IGNORECASE | re.DOTALL)
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        payload = json.loads(text)
    else:
        payload = value
    if (
        isinstance(payload, dict)
        and isinstance(payload.get("content"), str)
        and payload.get("type") in {"text", "output_text"}
    ):
        payload = _decode_json_message_content(payload["content"])
    if isinstance(payload, dict) and "summary" in payload and isinstance(payload.get("modules"), list):
        # Some model responses annotate the complete plan with a root `type`.
        # It carries no planning data; keep every other field for schema validation.
        payload = {key: item for key, item in payload.items() if key != "type"}
    return payload


def _parse_v2_compile_response(response: httpx.Response, error_code: str):
    try:
        envelope = response.json()
        content = envelope["choices"][0]["message"]["content"]
        output = json.loads(content)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise AppError(error_code, "模块规划模型返回的 V2 结构无效", 502) from None
    return parse_v2_result(output, error_code=error_code)


class OpenAICompatibleImageEditor:
    supports_multiple_source_images = True

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        timeout_ms: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout_ms = timeout_ms
        self._transport = transport

    @staticmethod
    def resolve_parameters(aspect_ratio: str, resolution: str) -> dict[str, str]:
        normalized_resolution = normalize_resolution(resolution)
        try:
            size = _IMAGE_SIZE_MAP[normalized_resolution][aspect_ratio.strip()]
        except KeyError:
            raise AppError(
                "IMAGE_PROVIDER_PARAMETERS_UNSUPPORTED",
                "image size is not supported by the configured provider",
                400,
            ) from None
        return {"size": size, "quality": "medium"}

    def describe_request(self, request: ImageEditRequest) -> dict[str, object]:
        parameters = self.resolve_parameters(request.aspect_ratio, request.resolution)
        return {
            "model": self._model,
            "endpoint": "/v1/images/edits",
            "size": parameters["size"],
            "quality": parameters["quality"],
            "n": 1,
            "responseFormat": "b64_json",
            "sourceImageCount": len(request.ordered_image_inputs()),
        }

    async def edit(self, request: ImageEditRequest) -> ImageEditResult:
        if not self._base_url or not self._api_key or not self._model:
            raise AppError(
                "IMAGE_PROVIDER_UNAVAILABLE",
                "image provider is not configured",
                503,
            )
        parameters = self.resolve_parameters(request.aspect_ratio, request.resolution)
        data = {
            "model": self._model,
            "prompt": request.prompt,
            "size": parameters["size"],
            "quality": parameters["quality"],
            "n": "1",
            "response_format": "b64_json",
        }
        files = [
            (
                "image",
                (item.image_filename, item.image_bytes, item.image_mime_type),
            )
            for item in request.ordered_image_inputs()
        ]
        timeout = httpx.Timeout(self._timeout_ms / 1000)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url.rstrip('/')}/images/edits" if self._base_url.rstrip('/').endswith('/v1') else f"{self._base_url.rstrip('/')}/v1/images/edits",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files=files,
                )
                if response.is_error:
                    if response.status_code == 504:
                        raise AppError("IMAGE_PROVIDER_TIMEOUT", "image provider timed out", 504)
                    raise AppError(
                        "IMAGE_PROVIDER_FAILED",
                        "image provider request failed",
                        502,
                    )
                image_bytes, image_mime_type = await _parse_image_edit_response(response, client)
        except httpx.TimeoutException:
            raise AppError("IMAGE_PROVIDER_TIMEOUT", "image provider timed out", 504) from None
        except httpx.RequestError:
            raise AppError(
                "IMAGE_PROVIDER_FAILED",
                "image provider request failed",
                502,
            ) from None

        return ImageEditResult(
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            provider_request=self.describe_request(request),
        )


async def _parse_image_edit_response(
    response: httpx.Response,
    client: httpx.AsyncClient,
) -> tuple[bytes, str]:
    try:
        payload = response.json()
        item = payload["data"][0]
        encoded = item.get("b64_json") if isinstance(item, dict) else None
        if isinstance(encoded, str) and encoded:
            # Some OpenAI-compatible gateways wrap the payload in a data URI,
            # while the Images API contract normally returns raw base64. Accept
            # both forms and tolerate line wrapping introduced by the gateway.
            if encoded.startswith("data:"):
                header, separator, encoded = encoded.partition(",")
                if not separator or ";base64" not in header.lower():
                    raise ValueError("invalid data URI image")
            image_bytes = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
        else:
            image_url = item.get("url") if isinstance(item, dict) else None
            parsed_url = urlsplit(image_url) if isinstance(image_url, str) else None
            if (
                not parsed_url
                or parsed_url.scheme not in {"http", "https"}
                or not parsed_url.netloc
            ):
                raise ValueError("missing image payload")
            image_response = await client.get(image_url)
            if image_response.is_error or not image_response.content:
                raise ValueError("image URL download failed")
            image_bytes = image_response.content
        mime_type, _, _, _ = inspect_image(
            image_bytes,
            None,
            _MAX_PROVIDER_IMAGE_BYTES,
        )
    except (AppError, IndexError, KeyError, TypeError, ValueError, binascii.Error):
        raise AppError(
            "IMAGE_PROVIDER_INVALID_RESPONSE",
            "image provider returned an invalid response",
            502,
        ) from None
    return image_bytes, mime_type
