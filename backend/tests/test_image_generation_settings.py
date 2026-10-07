import pytest

from backend.app.core.config import Settings


def test_settings_read_multimodal_prompt_compiler_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTEXT_BASE_URL", "https://vision.example.test/v1")
    monkeypatch.setenv("CONTEXT_API_KEY", "secret-value")
    monkeypatch.setenv("CONTEXT_MODEL", "vision-model")
    monkeypatch.setenv("CONTEXT_TIMEOUT_MS", "123000")

    settings = Settings(_env_file=None)

    assert settings.context_base_url == "https://vision.example.test/v1"
    assert settings.context_api_key == "secret-value"
    assert settings.context_model == "vision-model"
    assert settings.context_timeout_ms == 123000
    assert "secret-value" not in repr(settings)


def test_settings_allow_prompt_compiler_to_be_unconfigured() -> None:
    settings = Settings(_env_file=None)

    assert settings.context_base_url is None
    assert settings.context_api_key is None
    assert settings.context_model is None


def test_settings_default_to_three_adaptive_generation_workers() -> None:
    settings = Settings(_env_file=None)

    assert settings.generation_worker_poll_interval_ms == 1_000
    assert settings.generation_worker_lease_seconds == 60
    assert settings.generation_worker_concurrency == 3
    assert settings.generation_worker_claim_limit == 4
    assert settings.image_generation_timeout_ms == 1_800_000


def test_settings_read_generation_worker_limits_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENERATION_WORKER_POLL_INTERVAL_MS", "2500")
    monkeypatch.setenv("GENERATION_WORKER_LEASE_SECONDS", "90")
    monkeypatch.setenv("GENERATION_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("GENERATION_WORKER_CLAIM_LIMIT", "8")

    settings = Settings(_env_file=None)

    assert settings.generation_worker_poll_interval_ms == 2_500
    assert settings.generation_worker_lease_seconds == 90
    assert settings.generation_worker_concurrency == 2
    assert settings.generation_worker_claim_limit == 8
