from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .application.task_design import TaskDesignInput


class SuiteCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class ProjectCreate(BaseModel):
    name: str


class ProjectAssetSelectionInput(BaseModel):
    assetId: UUID


class GenerationConfigDraftReplace(BaseModel):
    baseVersion: int = Field(gt=0)
    content: dict[str, Any]


class HeroModuleParameterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=500)


class HeroPromptCompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceAssetId: UUID
    marketId: str = Field(min_length=1, max_length=100)
    modelId: str = Field(min_length=1, max_length=100)
    styleId: str = Field(min_length=1, max_length=100)
    moduleId: str = Field(min_length=1, max_length=100)
    aspectRatio: str = Field(min_length=1, max_length=20)
    resolution: str = Field(min_length=1, max_length=40)
    outputLanguage: str = Field(min_length=1, max_length=40)
    customStyle: str = Field(default="", max_length=1000)
    moduleParameters: list[HeroModuleParameterInput] = Field(default_factory=list, max_length=20)
    resultCount: Literal[1] = 1


class HeroGenerationConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskPrompt: str | None = Field(default=None, min_length=1, max_length=20000)


class BatchHeroModuleInput(BaseModel):
    taskDesign: TaskDesignInput | None = None
    model_config = ConfigDict(extra="forbid")

    moduleId: str = Field(min_length=1, max_length=100)
    taskId: str | None = Field(default=None, min_length=1, max_length=100)
    resultCount: int = Field(ge=1, le=4)
    moduleParameters: list[HeroModuleParameterInput] = Field(default_factory=list, max_length=20)
    reverseReference: "ReverseModuleReferenceInput | None" = None
    regularTask: dict[str, str] | None = None


class BatchHeroPromptCompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceAssetId: UUID
    marketId: str = Field(min_length=1, max_length=100)
    modelId: str = Field(min_length=1, max_length=100)
    styleId: str = Field(min_length=1, max_length=100)
    aspectRatio: str = Field(min_length=1, max_length=20)
    resolution: str = Field(min_length=1, max_length=40)
    outputLanguage: str = Field(min_length=1, max_length=40)
    customStyle: str = Field(default="", max_length=1000)
    modules: list[BatchHeroModuleInput] = Field(min_length=1, max_length=20)
    modulePlanId: UUID | None = None
    reverseVersionId: UUID | None = None
    creationMode: Literal["regular", "professional"] = "professional"
    userNotes: str = Field(default="", max_length=4000)


class BatchGenerationConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moduleTaskPrompts: dict[str, str] = Field(min_length=1)


class SuitePlanningReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referenceId: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)


class ReverseModuleReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: UUID
    moduleId: str = Field(min_length=1, max_length=200)


class SuitePlanModuleCompileInput(BaseModel):
    taskDesign: TaskDesignInput | None = None
    model_config = ConfigDict(extra="forbid")

    moduleId: str = Field(min_length=1, max_length=100)
    taskId: str | None = Field(default=None, min_length=1, max_length=100)
    resultCount: int = Field(ge=1, le=4)
    moduleParameters: list[HeroModuleParameterInput] = Field(default_factory=list, max_length=20)
    reverseReference: ReverseModuleReferenceInput | None = None
    regularTask: dict[str, str] | None = None


class SuitePlanCompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceAssetIds: list[UUID] = Field(min_length=1, max_length=4)
    marketId: str = Field(min_length=1, max_length=100)
    modelId: str = Field(min_length=1, max_length=100)
    styleId: str = Field(min_length=1, max_length=100)
    aspectRatio: str = Field(min_length=1, max_length=20)
    resolution: str = Field(min_length=1, max_length=40)
    outputLanguage: str = Field(min_length=1, max_length=40)
    modules: list[SuitePlanModuleCompileInput] = Field(min_length=1)
    modulePlanId: UUID | None = None
    reverseVersionId: UUID | None = None
    userNotes: str = Field(default="", max_length=4000)
    customStyle: str = Field(default="", max_length=500)
    creationMode: Literal["regular", "professional"] = "professional"
    references: list[SuitePlanningReferenceInput] = Field(default_factory=list, max_length=20)


class SuitePlanModulePatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expectedPlanRevision: int = Field(gt=0)
    expectedModuleRevision: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    copySummary: str | None = Field(default=None, max_length=20000)
    visualDirection: str | None = Field(default=None, max_length=20000)
    currentTaskPrompt: str | None = Field(default=None, min_length=1, max_length=20000)
    resultCount: int | None = Field(default=None, ge=1, le=4)
    moduleParameters: list[HeroModuleParameterInput] | None = Field(default=None, max_length=20)


class SuitePlanOrderPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expectedPlanRevision: int = Field(gt=0)
    moduleIds: list[UUID] = Field(min_length=1)


class SuitePlanConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expectedPlanRevision: int = Field(gt=0)
    moduleTaskPrompts: dict[str, str] = Field(min_length=1)


class WorkbenchTaskPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expectedRevision: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    purpose: str | None = Field(default=None, max_length=20000)
    promptDraft: str | None = Field(default=None, max_length=20000)
    sourceInputImageId: UUID | None = None
    generationParams: dict[str, Any] | None = None


class WorkbenchGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expectedRevision: int | None = Field(default=None, gt=0)
    promptDraft: str | None = Field(default=None, max_length=20000)


class WorkbenchBatchGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskIds: list[UUID] | None = Field(default=None, max_length=100)


class WorkbenchTaskItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planItemId: UUID
    ordinal: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=300)
    purpose: str = Field(default="", max_length=20000)
    promptDraft: str = Field(default="", max_length=20000)
    generationParams: dict[str, Any] = Field(default_factory=dict)
    imageType: Literal["main", "detail"] = "detail"
    sourceInputImageId: UUID | None = None


class WorkbenchTaskCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planSnapshotId: UUID
    tasks: list[WorkbenchTaskItemInput] | None = Field(default=None, max_length=100)


class WorkbenchLayoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layoutVersion: int = Field(ge=0)
    viewport: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    groups: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class WorkbenchReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetType: Literal["plan", "task"]
    targetId: UUID
    resourceType: str = Field(min_length=1, max_length=40)
    resourceId: UUID
    resourceVersion: str = Field(default="", max_length=120)
    sourceSnapshot: dict[str, Any] = Field(default_factory=dict)


class InputImageOut(BaseModel):
    id: UUID
    suiteId: UUID
    ordinal: int
    sha256: str
    width: int
    height: int
    mimeType: str
    originalFilename: str
    createdAt: datetime
    originalPreviewUrl: str
    thumbnailPreviewUrl: str


class SuiteOut(BaseModel):
    id: UUID
    name: str
    status: str
    createdAt: datetime
    updatedAt: datetime


class SuiteAggregate(SuiteOut):
    inputImages: list[InputImageOut] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    requestId: str


class ResponseEnvelope(BaseModel):
    data: Any
    requestId: str
