from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ImageEditInput:
    image_bytes: bytes
    image_mime_type: str
    image_filename: str


@dataclass(frozen=True)
class PromptCompileRequest:
    system_prompt: str
    user_prompt: str
    image_bytes: bytes
    image_mime_type: str
    planner_version: Literal["v2"] = "v2"
    image_inputs: tuple[ImageEditInput, ...] = ()

    def ordered_image_inputs(self) -> tuple[ImageEditInput, ...]:
        if self.image_inputs:
            return self.image_inputs
        return (
            ImageEditInput(
                self.image_bytes,
                self.image_mime_type,
                "source.png",
            ),
        )


class PromptCompilerPort(Protocol):
    async def compile(self, request: PromptCompileRequest) -> object: ...


@dataclass(frozen=True)
class ImageEditRequest:
    prompt: str
    image_bytes: bytes
    image_mime_type: str
    image_filename: str
    aspect_ratio: str
    resolution: str
    image_inputs: tuple[ImageEditInput, ...] = ()
    model_connection: dict | None = None
    background: Literal["transparent", "opaque", "auto"] | None = None

    def ordered_image_inputs(self) -> tuple[ImageEditInput, ...]:
        if self.image_inputs:
            return self.image_inputs
        return (
            ImageEditInput(
                self.image_bytes,
                self.image_mime_type,
                self.image_filename,
            ),
        )


@dataclass(frozen=True)
class ImageEditResult:
    image_bytes: bytes
    image_mime_type: str
    provider_request: dict[str, object]


class ImageEditorPort(Protocol):
    def describe_request(self, request: ImageEditRequest) -> dict[str, object]: ...

    async def edit(self, request: ImageEditRequest) -> ImageEditResult: ...
