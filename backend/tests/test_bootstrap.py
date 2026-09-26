from importlib import import_module


def test_fastapi_application_module_is_importable() -> None:
    module = import_module("backend.app.main")
    assert callable(module.create_app)
