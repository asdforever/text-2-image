import pytest

from backend.app.core.config import Settings
from backend.app.image_processing import inspect_image


def test_production_settings_fail_without_secrets() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(environment="production", _env_file=None).validate_startup()


def test_image_validation_rejects_mime_mismatch() -> None:
    with pytest.raises(Exception) as error:
        inspect_image(b"not-an-image", "image/png", 1024)
    assert getattr(error.value, "code", None) == "INVALID_IMAGE"
