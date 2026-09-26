"""Bind a planning compiler to one immutable model connection."""
from dataclasses import dataclass
from typing import Any

from .openai_compatible import OpenAIChatProvider


@dataclass(frozen=True)
class BoundPromptModels:
    snapshot: dict[str, str] | None
    compiler: Any


class PromptModelResolver:
    def __init__(self, connections):
        self.connections = connections

    async def bind(self, published_config, compiler):
        if not isinstance(compiler, OpenAIChatProvider):
            return BoundPromptModels(None, compiler)
        snapshot = await self.connections.prompt_snapshot(published_config.get("promptModel"))
        connection = await self.connections.resolve_prompt(snapshot)
        return BoundPromptModels(snapshot, compiler.with_connection(connection))
