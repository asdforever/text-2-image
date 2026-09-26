from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Request

from .config import Settings


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """由服务端解析出的当前操作者和工作区范围。"""

    actor_id: UUID
    workspace_id: UUID
    role: str


class IdentityProvider(Protocol):
    def get_context(self) -> IdentityContext:
        ...


class LocalSingleUserIdentityProvider(IdentityProvider):
    def __init__(self, context: IdentityContext) -> None:
        self._context = context

    @classmethod
    def from_settings(cls, settings: Settings) -> "LocalSingleUserIdentityProvider":
        return cls(
            IdentityContext(
                actor_id=settings.local_actor_id,
                workspace_id=settings.local_workspace_id,
                role=settings.local_role,
            )
        )

    def get_context(self) -> IdentityContext:
        return self._context


def get_identity_provider(request: Request) -> IdentityProvider:
    provider = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        raise RuntimeError("identity provider is not configured")
    return provider


def get_identity_context(request: Request) -> IdentityContext:
    return get_identity_provider(request).get_context()
