"""使用任务冻结的连接版本发送请求；不将凭据放入请求快照。"""
from ..application.model_connection_service import validate_model_dimensions
from .openai_compatible import OpenAICompatibleImageEditor


class ConfiguredImageEditor:
    supports_multiple_source_images = True

    def __init__(self, connections, *, timeout_ms, transport=None):
        self.connections = connections
        self.timeout_ms, self.transport = timeout_ms, transport

    async def snapshot(self, model=None):
        return await self.connections.snapshot(model)

    def describe_request(self, request):
        snapshot = request.model_connection or {}
        validate_model_dimensions(snapshot, request.aspect_ratio, request.resolution)
        model_name = snapshot.get("modelName", self.connections.settings.image_generation_model)
        editor = OpenAICompatibleImageEditor(base_url=None, api_key=None, model=model_name, timeout_ms=self.timeout_ms)
        result = editor.describe_request(request)
        if snapshot.get("connectionId"):
            result["connectionId"] = snapshot["connectionId"]
        return result

    async def edit(self, request):
        snapshot = request.model_connection
        validate_model_dimensions(snapshot, request.aspect_ratio, request.resolution)
        # 仅未升级的历史任务可以使用环境连接，不静默套用新发布模型。
        resolved = await self.connections.resolve(snapshot) if snapshot else self.connections.environment()
        editor = OpenAICompatibleImageEditor(base_url=resolved.base_url, api_key=resolved.api_key, model=resolved.model_name,
            timeout_ms=self.timeout_ms, transport=self.transport)
        return await editor.edit(request)
