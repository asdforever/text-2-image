from dataclasses import replace
import os
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.app.core.config import Settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.errors import AppError
from backend.app.application.model_connection_service import ModelConnectionService
from backend.app.model_connection_repository import MemoryModelConnectionRepository
from backend.app.core.model_secrets import ModelSecretCodec


def fixture():
    settings = Settings(_env_file=None, model_connection_encryption_key=Fernet.generate_key().decode(),
        image_generation_base_url="https://legacy.example", image_generation_api_key="legacy-private", image_generation_model="legacy-image")
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), uuid4(), "owner"))
    repository = MemoryModelConnectionRepository()
    return ModelConnectionService(repository, identity, settings), repository, settings, identity


@pytest.mark.skipif(os.name != "nt", reason="Windows 默认密钥存储")
def test_windows_key_survives_codec_recreation_without_plaintext_storage():
    encrypted = ModelSecretCodec().encrypt("本机模拟凭据-test-only")
    assert b"test-only" not in encrypted
    assert encrypted.startswith(b"dpapi:")
    assert ModelSecretCodec().decrypt(encrypted) == "本机模拟凭据-test-only"


def test_invalid_server_encryption_key_returns_safe_configuration_error():
    with pytest.raises(AppError) as caught:
        ModelSecretCodec("invalid-secret").encrypt("private")
    assert caught.value.code == "MODEL_SECRET_KEY_INVALID"
    assert "private" not in str(caught.value) and "invalid-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_connection_versions_are_encrypted_scoped_and_never_return_secrets():
    service, repo, settings, identity = fixture()
    first = await service.create({"baseUrl": "https://one.example/v1/", "modelName": "image-a", "protocol": "openai_images", "apiKey": "private-one"})
    second = await service.create({"baseUrl": "https://two.example", "modelName": "image-b", "protocol": "openai_images", "reuseConnectionId": first["id"]})
    assert first["id"] != second["id"]
    assert first["hasApiKey"] and "private-one" not in str(await service.list())
    record = await repo.get(UUID(first["id"]), identity.get_context().workspace_id)
    assert b"private-one" not in record.encrypted_key
    frozen = await service.snapshot({"id": "preset-a", "connectionId": first["id"]})
    resolved = await service.resolve(frozen)
    assert resolved.model_name == "image-a" and resolved.api_key == "private-one"
    assert "private-one" not in repr(resolved) and "private-one" not in str(frozen)
    other = LocalSingleUserIdentityProvider(replace(identity.get_context(), workspace_id=uuid4()))
    with pytest.raises(AppError):
        await ModelConnectionService(repo, other, settings).resolve(frozen)


@pytest.mark.asyncio
async def test_environment_is_frozen_and_new_connection_does_not_change_old_task():
    service, repo, settings, identity = fixture()
    frozen = await service.snapshot({"id": "old", "provider": "OpenAI"})
    settings.image_generation_api_key = "changed-private"
    settings.image_generation_model = "changed-model"
    restarted = ModelConnectionService(repo, identity, settings)
    resolved = await restarted.resolve(frozen)
    assert resolved.api_key == "legacy-private" and resolved.model_name == "legacy-image"
    updated = await restarted.create({"baseUrl": "https://new.example", "modelName": "new-image", "protocol": "openai_images", "reuseConnectionId": "environment"})
    assert (await restarted.resolve({"connectionId": updated["id"]})).api_key == "changed-private"


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"baseUrl":"https://user:private@bad.example"}, {"baseUrl":"file:///tmp/x"}, {"baseUrl":"https://x.example?key=private"}, {"protocol":"unsupported"}, {"apiKey":""}])
async def test_invalid_connection_does_not_persist_or_echo_secrets(patch):
    service, _, _, _ = fixture()
    with pytest.raises(AppError) as error:
        await service.create({"baseUrl":"https://x.example", "modelName":"image", "protocol":"openai_images", "apiKey":"private", **patch})
    assert "private" not in str(error.value)
    assert len(await service.list()) == 1  # 环境连接仅提供配置状态。


@pytest.mark.asyncio
async def test_selected_connection_controls_http_model_key_and_endpoint():
    import base64
    from backend.tests.test_canvas_generation import png
    from backend.app.providers.configured_image_editor import ConfiguredImageEditor
    from backend.app.application.hero_generation_ports import ImageEditRequest
    service, _, settings, _ = fixture()
    first = await service.create({"baseUrl":"https://one.example/v1", "modelName":"actual-image", "protocol":"openai_images", "apiKey":"private"})
    frozen = await service.snapshot({"id":"selected", "connectionId":first["id"]})
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data":[{"b64_json":base64.b64encode(png("blue")).decode()}]})
    editor = ConfiguredImageEditor(service, timeout_ms=1000, transport=httpx.MockTransport(respond))
    request = ImageEditRequest("商品", b"source", "image/png", "source.png", "1:1", "标准 1K", model_connection=frozen)
    await editor.edit(request)
    assert str(calls[0].url) == "https://one.example/v1/images/edits"
    assert calls[0].headers["Authorization"] == "Bearer private"
    assert b"actual-image" in calls[0].content
    assert editor.describe_request(request)["model"] == "actual-image"
    assert "private" not in str(editor.describe_request(request))


@pytest.mark.asyncio
async def test_prompt_test_uses_frozen_connection_and_sanitizes_provider_errors(monkeypatch, caplog):
    from backend.app.test_executor import TestExecutor
    service, _, _, _ = fixture()
    connection = await service.create({"baseUrl":"https://test.example/v1", "modelName":"test-image", "protocol":"openai_images", "apiKey":"secret-test-key"})
    snapshot = await service.snapshot({"connectionId":connection["id"]})
    executor = TestExecutor(None, None, api_base_url="https://wrong.example", api_key="wrong-key")
    executor.model_connections = service
    calls = []
    real_client = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return httpx.Response(403, text="upstream leaked secret-test-key")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)))
    with pytest.raises(ValueError) as error:
        await executor._call_image_api("产品", generation_params={"modelConnection":snapshot})
    assert str(calls[0].url) == "https://test.example/v1/images/generations"
    assert calls[0].headers["Authorization"] == "Bearer secret-test-key"
    assert b"test-image" in calls[0].content
    assert "secret-test-key" not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_public_connection_api_never_echoes_key():
    from backend.app.main import create_app
    service, _, settings, identity = fixture()
    app = create_app(settings=Settings(_env_file=None), identity_provider=identity)
    app.state.model_connection_service = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/model-connections", json={"baseUrl":"https://test.example", "modelName":"image", "protocol":"openai_images", "apiKey":"private-api-key"})
        assert result.status_code == 201
        listing = await client.get("/api/model-connections")
        assert listing.status_code == 200
        assert "private-api-key" not in result.text + listing.text
        assert result.json()["data"]["hasApiKey"] is True
