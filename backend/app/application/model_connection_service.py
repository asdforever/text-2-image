from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

from ..core.errors import AppError
from ..core.image_dimensions import RESOLUTION_LEVELS, normalize_resolution
from ..core.model_secrets import ModelSecretCodec
from ..model_connection_repository import ModelConnectionRecord


@dataclass(frozen=True)
class ResolvedModelConnection:
    base_url: str
    model_name: str
    protocol: str
    api_key: str = field(repr=False)


def normalized_base_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(c.isspace() for c in value.strip()):
        raise AppError("MODEL_CONNECTION_INVALID", "请填写有效的接口地址", 400)
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
        _ = parsed.port
    except ValueError:
        raise AppError("MODEL_CONNECTION_INVALID", "接口地址须为 HTTP(S) 地址，且不含账号、密钥、查询参数或片段", 400) from None
    return value.strip().rstrip("/")


def image_endpoint(base_url, operation="edits"):
    base = base_url.rstrip("/")
    return f"{base}/images/{operation}" if base.endswith("/v1") else f"{base}/v1/images/{operation}"


def validate_model_dimensions(snapshot, aspect_ratio, resolution):
    """按任务冻结的能力校验，旧快照没有限制时保留原行为。"""
    snapshot = snapshot or {}
    if snapshot.get("aspectRatios") and aspect_ratio not in snapshot["aspectRatios"]:
        raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "所选模型不支持此图片比例，请修改生成参数", 400)
    if snapshot.get("resolutions") and normalize_resolution(resolution) not in {normalize_resolution(item) for item in snapshot["resolutions"]}:
        raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "所选模型不支持此分辨率，请修改生成参数", 400)


def model_selection_id(value):
    """外部选择只能是目录标识，不能注入内部历史连接快照。"""
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise AppError("MODEL_SELECTION_INVALID", "请选择已发布配置中的模型", 400)
    return value


class ModelConnectionService:
    def __init__(self, repository, identity, settings, generation_config=None):
        self.repository, self.identity, self.settings = repository, identity, settings
        self.generation_config = generation_config
        self.codec = ModelSecretCodec(settings.model_connection_encryption_key)

    @property
    def workspace(self):
        return self.identity.get_context().workspace_id

    @staticmethod
    def view(record):
        return {"id":str(record.id), "baseUrl":record.base_url, "modelName":record.model_name,
            "protocol":record.protocol, "hasApiKey":True, "createdAt":record.created_at.isoformat()}

    def environment(self):
        cfg = self.settings
        if not cfg.image_generation_base_url or not cfg.image_generation_api_key:
            raise AppError("MODEL_CONNECTION_REQUIRED", "请先在生成配置中设置模型接口地址和 API Key，并发布配置", 409)
        return ResolvedModelConnection(normalized_base_url(cfg.image_generation_base_url), cfg.image_generation_model, "openai_images", cfg.image_generation_api_key)

    def prompt_environment(self):
        cfg = self.settings
        if not cfg.context_base_url or not cfg.context_api_key or not cfg.context_model:
            raise AppError("PROMPT_MODEL_REQUIRED", "请先配置提示词模型并发布，或设置服务端 context 模型", 409)
        return ResolvedModelConnection(normalized_base_url(cfg.context_base_url), cfg.context_model, "openai_chat", cfg.context_api_key)

    async def list(self):
        records = [self.view(item) for item in await self.repository.list(self.workspace)]
        if self.settings.image_generation_base_url and self.settings.image_generation_api_key:
            env = self.environment()
            records.append({"id":"environment", "baseUrl":env.base_url, "modelName":env.model_name,
                "protocol":env.protocol, "hasApiKey":True, "createdAt":None})
        if self.settings.context_base_url and self.settings.context_api_key and self.settings.context_model:
            env = self.prompt_environment()
            records.append({"id":"environment-context", "baseUrl":env.base_url, "modelName":env.model_name,
                "protocol":env.protocol, "hasApiKey":True, "createdAt":None})
        return records

    async def _record(self, connection_id):
        try:
            parsed = UUID(str(connection_id))
        except ValueError:
            raise AppError("MODEL_CONNECTION_NOT_FOUND", "模型连接不存在或不可用", 404) from None
        record = await self.repository.get(parsed, self.workspace)
        if record is None:
            raise AppError("MODEL_CONNECTION_NOT_FOUND", "模型连接不存在或不属于当前工作区", 404)
        return record

    async def create(self, payload):
        allowed = {"baseUrl", "modelName", "protocol", "apiKey", "reuseConnectionId"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise AppError("MODEL_CONNECTION_INVALID", "模型连接字段无效", 400)
        base_url = normalized_base_url(payload.get("baseUrl"))
        model = payload.get("modelName")
        if not isinstance(model, str) or not model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
            raise AppError("MODEL_CONNECTION_INVALID", "请填写实际请求的模型名称，最多 200 个字符", 400)
        protocol = payload.get("protocol")
        if not isinstance(protocol, str) or protocol not in {"openai_images", "openai_chat"}:
            raise AppError("MODEL_CONNECTION_INVALID", "请选择 OpenAI 兼容图片或对话接口", 400)
        key = payload.get("apiKey")
        if key is not None and (not isinstance(key, str) or len(key) > 8192 or any(ord(c) < 32 for c in key)):
            raise AppError("MODEL_CONNECTION_INVALID", "API Key 格式无效", 400)
        if not key or not key.strip():
            reference = payload.get("reuseConnectionId")
            if reference is not None and not isinstance(reference, str):
                raise AppError("MODEL_CONNECTION_INVALID", "复用连接标识格式无效", 400)
            if reference in {"environment", "environment-context"}:
                source = self.environment() if reference == "environment" else self.prompt_environment()
                self._require_protocol(source, protocol)
                key = source.api_key
            elif reference:
                source = await self._record(reference)
                self._require_protocol(source, protocol)
                key = self.codec.decrypt(source.encrypted_key)
            else:
                raise AppError("MODEL_CONNECTION_KEY_REQUIRED", "新模型连接需要填写 API Key", 400)
        record = ModelConnectionRecord(uuid4(), self.workspace, base_url, model.strip(), protocol, self.codec.encrypt(key.strip()))
        return self.view(await self.repository.insert(record))

    async def snapshot(self, model=None):
        if model is None or isinstance(model, str):
            if self.generation_config:
                published = await self.generation_config.get_published()
                models = published.content.get("models", [])
                selected = next((item for item in models if item["id"] == model), None) if model else next(iter(models), None)
                if model and selected is None:
                    raise AppError("MODEL_CONNECTION_NOT_FOUND", "所选模型不在已发布配置中", 404)
                model = selected
            elif model:
                raise AppError("MODEL_CONNECTION_NOT_FOUND", "所选模型不存在", 404)
        model = model or {}
        resolutions = [normalize_resolution(item) for item in model.get("resolutions", [])]
        if any(item not in RESOLUTION_LEVELS for item in resolutions):
            raise AppError("MODEL_CAPABILITIES_INVALID", "请在生成配置中将模型分辨率设为 1K、2K 或 4K", 400)
        connection_id = model.get("connectionId")
        if connection_id and connection_id != "environment":
            record = await self._record(connection_id)
            self._require_protocol(record, "openai_images")
        else:
            if str(model.get("provider", "OpenAI")).lower() != "openai":
                raise AppError("MODEL_CONNECTION_REQUIRED", "此模型尚未配置接口地址和 API Key", 409)
            env = self.environment()
            digest = sha256((env.base_url + "\0" + env.model_name + "\0" + env.api_key).encode()).hexdigest()
            record_id = uuid5(self.workspace, digest)
            record = await self.repository.get(record_id, self.workspace)
            if record is None:
                record = await self.repository.insert(ModelConnectionRecord(record_id, self.workspace, env.base_url, env.model_name, env.protocol, self.codec.encrypt(env.api_key)))
        return {"connectionId":str(record.id), "baseUrl":record.base_url, "modelName":record.model_name, "protocol":record.protocol,
            **({"resolutions":resolutions} if resolutions else {}),
            **({"aspectRatios":list(model["aspectRatios"])} if model.get("aspectRatios") else {}),
            **({"modelId":model["id"]} if model.get("id") else {})}

    async def resolve(self, snapshot):
        connection_id = snapshot.get("connectionId") if isinstance(snapshot, dict) else None
        # Environment-derived connections use a deterministic id. Resolve that
        # id directly so a legacy DPAPI/Fernet payload can never block an old
        # task after the backend user or encryption key changes.
        try:
            environment = self.environment()
        except AppError:
            environment = None
        if environment is not None and connection_id == str(
            uuid5(
                self.workspace,
                sha256(
                    (environment.base_url + "\0" + environment.model_name + "\0" + environment.api_key).encode()
                ).hexdigest(),
            )
        ):
            return environment
        record = await self._record(snapshot.get("connectionId"))
        self._require_protocol(record, "openai_images")
        return ResolvedModelConnection(
            record.base_url,
            record.model_name,
            record.protocol,
            self._decrypt_record_key(record, "openai_images"),
        )

    @staticmethod
    def _require_protocol(connection, protocol):
        if connection.protocol != protocol:
            raise AppError("MODEL_CONNECTION_PROTOCOL_INVALID", "模型连接的接口协议不符合用途", 400)

    async def prompt_snapshot(self, selection=None):
        """Resolve an explicit selection from one published config; never re-read it."""
        connection_id = (selection or {}).get("connectionId")
        if connection_id and connection_id != "environment-context":
            record = await self._record(connection_id)
            self._require_protocol(record, "openai_chat")
        else:
            env = self.prompt_environment()
            digest = sha256((env.protocol + "\0" + env.base_url + "\0" + env.model_name + "\0" + env.api_key).encode()).hexdigest()
            record_id = uuid5(self.workspace, digest)
            record = await self.repository.get(record_id, self.workspace)
            if record is None:
                record = await self.repository.insert(ModelConnectionRecord(record_id, self.workspace, env.base_url, env.model_name, env.protocol, self.codec.encrypt(env.api_key)))
        return {"connectionId": str(record.id), "baseUrl": record.base_url,
                "modelName": record.model_name, "protocol": record.protocol}

    async def resolve_prompt(self, snapshot):
        record = await self._record(snapshot.get("connectionId"))
        self._require_protocol(record, "openai_chat")
        return ResolvedModelConnection(
            record.base_url,
            record.model_name,
            record.protocol,
            self._decrypt_record_key(record, "openai_chat"),
        )

    def _decrypt_record_key(self, record, protocol):
        try:
            return self.codec.decrypt(record.encrypted_key)
        except AppError as exc:
            if exc.code != "MODEL_SECRET_UNAVAILABLE":
                raise
            # Environment-derived connections are persisted so task snapshots
            # can remain immutable. If their legacy DPAPI value cannot be opened
            # after a user/profile change, the current environment credential is
            # still the same connection and can be used safely.
            try:
                environment = self.environment() if protocol == "openai_images" else self.prompt_environment()
            except AppError:
                raise
            if (
                record.protocol != environment.protocol
                or record.base_url != environment.base_url
                or record.model_name != environment.model_name
            ):
                raise
            return environment.api_key
