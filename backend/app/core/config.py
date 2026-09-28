from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "PicAgent API"
    # Accept both the FastAPI-native ENVIRONMENT and the existing frontend
    # convention NODE_ENV.  ENVIRONMENT takes precedence when both are set.
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("environment", "ENVIRONMENT", "NODE_ENV"),
    )
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str | None = None
    pg_host: str | None = None
    pg_port: int = 5432
    pg_database: str | None = None
    pg_user: str | None = None
    pg_password: str | None = Field(default=None, repr=False)
    minio_endpoint: str | None = None
    minio_access_key: str | None = Field(default=None, repr=False)
    minio_secret_key: str | None = Field(default=None, repr=False)
    minio_bucket: str | None = None
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    max_upload_bytes: int = 12 * 1024 * 1024
    image_generation_base_url: str | None = None
    image_generation_api_key: str | None = Field(default=None, repr=False)
    image_generation_model: str = "gpt-image-2"
    image_generation_timeout_ms: int = 600000
    model_connection_encryption_key: str | None = Field(default=None, repr=False)
    generation_worker_poll_interval_ms: int = Field(default=1_000, ge=100)
    generation_worker_lease_seconds: int = Field(default=60, ge=1)
    generation_worker_concurrency: int = Field(default=3, ge=1)
    generation_worker_claim_limit: int = Field(default=4, ge=1)
    context_base_url: str | None = None
    context_api_key: str | None = Field(default=None, repr=False)
    context_model: str | None = None
    context_timeout_ms: int = 600000
    local_actor_id: UUID = UUID("11111111-1111-4111-8111-111111111111")
    local_workspace_id: UUID = UUID("22222222-2222-4222-8222-222222222222")
    local_role: str = "owner"

    @model_validator(mode="after")
    def build_database_url(self):
        if not self.database_url and all((self.pg_host, self.pg_database, self.pg_user, self.pg_password)):
            self.database_url = "postgresql+asyncpg://{}:{}@{}:{}/{}".format(
                quote(self.pg_user or "", safe=""), quote(self.pg_password or "", safe=""), self.pg_host, self.pg_port, self.pg_database
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def validate_startup(self) -> None:
        if self.environment.lower() in {"production", "staging"}:
            required = {
                "DATABASE_URL": self.database_url,
                "MINIO_ENDPOINT": self.minio_endpoint,
                "MINIO_ACCESS_KEY": self.minio_access_key,
                "MINIO_SECRET_KEY": self.minio_secret_key,
                "MINIO_BUCKET": self.minio_bucket,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("PORT must be between 1 and 65535")


@lru_cache
def get_settings() -> Settings:
    return Settings()
