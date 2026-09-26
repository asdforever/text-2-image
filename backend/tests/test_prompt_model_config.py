from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.app.application.model_connection_service import ModelConnectionService
from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_catalog import create_default_generation_config, normalize_generation_config
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.model_connection_repository import MemoryModelConnectionRepository
from backend.tests.test_generation_config_service import _service


def connections(identity=None, **overrides):
    settings = Settings(
        _env_file=None, database_url=None, pg_host=None,
        model_connection_encryption_key=Fernet.generate_key().decode(),
        context_base_url="https://legacy-chat.example/v1", context_model="legacy-chat",
        context_api_key="private-context-key", **overrides,
    )
    identity = identity or LocalSingleUserIdentityProvider(IdentityContext(uuid4(), uuid4(), "owner"))
    return ModelConnectionService(MemoryModelConnectionRepository(), identity, settings)


def chat_payload(model="vision-a", **overrides):
    return dict(baseUrl="https://chat.example", modelName=model, protocol="openai_chat", apiKey="private-chat-key", **overrides)


@pytest.mark.asyncio
async def test_chat_connections_encrypt_reuse_and_redact_keys_in_public_api():
    from backend.app.main import create_app
    service = connections()
    app = create_app(settings=Settings(_env_file=None, database_url=None, pg_host=None))
    app.state.model_connection_service = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/model-connections", json=chat_payload())
        assert first.status_code == 201
        payload = chat_payload("vision-b")
        payload.update(apiKey="", reuseConnectionId=first.json()["data"]["id"])
        second = await client.post("/api/model-connections", json=payload)
        assert second.status_code == 201
        listing = await client.get("/api/model-connections")
    assert "private-chat-key" not in first.text + second.text + listing.text
    assert "private-context-key" not in listing.text
    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    record = await service._record(second.json()["data"]["id"])
    assert b"private-chat-key" not in record.encrypted_key
    assert service.codec.decrypt(record.encrypted_key) == "private-chat-key"
    assert any(item["id"] == "environment-context" and item["protocol"] == "openai_chat" for item in listing.json()["data"])


def test_prompt_model_roundtrip_and_legacy_fallback():
    config = create_default_generation_config()
    config["promptModel"] = {"connectionId": str(UUID(int=123))}
    assert normalize_generation_config(config)["promptModel"] == {"connectionId": str(UUID(int=123))}
    config.pop("promptModel")
    assert normalize_generation_config(config)["promptModel"] is None


@pytest.mark.parametrize("value", [{}, "connection", {"connectionId": ""}, {"connectionId": 3}, {"connectionId": "x", "apiKey": "secret"}])
def test_prompt_model_rejects_invalid_shape_and_credentials(value):
    config = create_default_generation_config()
    config["promptModel"] = value
    with pytest.raises(AppError):
        normalize_generation_config(config)


@pytest.mark.asyncio
async def test_publish_validates_chat_protocol_and_workspace_and_preserves_draft_lifecycle():
    config = _service(InMemoryGenerationConfigRepository(), 11)
    service = connections(config.identity_provider)
    config.model_connections = service
    first = await service.create(chat_payload())
    published = await config.get_published()
    content = deepcopy(published.content)
    content["promptModel"] = {"connectionId": first["id"]}
    draft = await config.replace_draft(content, published.version_no)
    assert draft.content["promptModel"] == content["promptModel"]
    assert (await config.get_published()).content.get("promptModel") is None
    saved = await config.publish()
    assert saved.content["promptModel"] == content["promptModel"]
    image = await service.create(dict(baseUrl="https://images.example", modelName="image", protocol="openai_images", apiKey="image-key"))
    foreign_identity = LocalSingleUserIdentityProvider(replace(config.identity_provider.get_context(), workspace_id=uuid4()))
    foreign = ModelConnectionService(service.repository, foreign_identity, service.settings)
    other = await foreign.create(chat_payload())
    for invalid in [image["id"], other["id"], str(uuid4()), "environment"]:
        content["promptModel"] = {"connectionId": invalid}
        await config.replace_draft(content, saved.version_no)
        with pytest.raises(AppError):
            await config.publish()
    content["promptModel"] = None
    await config.replace_draft(content, saved.version_no)
    assert (await config.publish()).content["promptModel"] is None


@pytest.mark.asyncio
async def test_chat_connections_cannot_be_used_by_image_snapshot_or_resolver():
    service = connections()
    chat = await service.create(chat_payload())
    with pytest.raises(AppError):
        await service.snapshot({"connectionId": chat["id"]})
    with pytest.raises(AppError):
        await service.resolve({"connectionId": chat["id"]})


@pytest.mark.asyncio
async def test_context_environment_key_can_be_reused_only_for_chat():
    service = connections()
    payload = chat_payload()
    payload.update(apiKey="", reuseConnectionId="environment-context")
    chat = await service.create(payload)
    assert service.codec.decrypt((await service._record(chat["id"])).encrypted_key) == "private-context-key"
    payload.update(protocol="openai_images")
    with pytest.raises(AppError):
        await service.create(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("protocol", {}), ("protocol", []), ("reuseConnectionId", {}), ("reuseConnectionId", [])])
async def test_connection_rejects_malformed_protocol_or_key_reuse_reference(field, value):
    service = connections()
    payload = chat_payload()
    payload.update(apiKey="")
    payload[field] = value
    with pytest.raises(AppError) as error:
        await service.create(payload)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_publish_cannot_bypass_prompt_connection_validation_when_service_unavailable():
    config = _service(InMemoryGenerationConfigRepository(), 11)
    published = await config.get_published()
    content = deepcopy(published.content)
    content["promptModel"] = {"connectionId": str(uuid4())}
    await config.replace_draft(content, published.version_no)
    with pytest.raises(AppError) as error:
        await config.publish()
    assert error.value.status_code == 503
