from uuid import UUID

import pytest

from backend.app.core.config import Settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider


ACTOR_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_local_identity_provider_returns_configured_context() -> None:
    settings = Settings(local_actor_id=ACTOR_ID, local_workspace_id=WORKSPACE_ID, local_role="owner")

    provider = LocalSingleUserIdentityProvider.from_settings(settings)

    assert provider.get_context() == IdentityContext(
        actor_id=ACTOR_ID,
        workspace_id=WORKSPACE_ID,
        role="owner",
    )


def test_local_identity_provider_is_stable_and_context_is_immutable() -> None:
    settings = Settings(local_actor_id=ACTOR_ID, local_workspace_id=WORKSPACE_ID)
    provider = LocalSingleUserIdentityProvider.from_settings(settings)

    first = provider.get_context()
    second = provider.get_context()

    assert first is second
    with pytest.raises((AttributeError, TypeError)):
        first.workspace_id = UUID("33333333-3333-4333-8333-333333333333")  # type: ignore[misc]


def test_settings_have_stable_local_identity_defaults() -> None:
    first = Settings()
    second = Settings()

    assert first.local_actor_id == second.local_actor_id
    assert first.local_workspace_id == second.local_workspace_id
    assert first.local_role == "owner"
