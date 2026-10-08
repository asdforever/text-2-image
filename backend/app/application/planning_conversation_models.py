"""Explicit identity passed to every conversation persistence operation."""
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

@dataclass(frozen=True)
class ConversationScope:
    workspace_id: UUID
    project_id: UUID
    mode: Literal['hero', 'suite']
    creation_mode: Literal['regular', 'professional']

    def __post_init__(self):
        if self.mode not in ('hero', 'suite') or self.creation_mode not in ('regular', 'professional'):
            raise ValueError('Invalid conversation scope')
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .module_planning_service import ModulePlanInput, RegularModule, RegularOutput

class EffectiveRegularModule(RegularModule):
    """Current manual goals retain the existing generation form's 2000 limit."""
    reason: str = Field(min_length=1, max_length=2000)

class EffectiveRegularOutput(RegularOutput):
    modules: list[EffectiveRegularModule] = Field(min_length=1, max_length=8)

class Wire(BaseModel):
    model_config = ConfigDict(extra='forbid')

class EffectiveSnapshot(Wire):
    plan: dict[str, Any]
    generationSettings: dict[str, Any] | None = None
    parameterOverrides: dict[str, list[dict[str,str]]] = Field(default_factory=dict)
    regularOptions: dict[str, dict[str,Any]] = Field(default_factory=dict)
    taskDesignOverrides: dict[str, dict[str,Any]] = Field(default_factory=dict)

    @model_validator(mode='wrap')
    @classmethod
    def controlled_snapshot_errors(cls, value, handler):
        from ..core.errors import AppError
        try:
            return handler(value)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AppError('CONVERSATION_SNAPSHOT_INVALID', '当前方案或参数格式无效，请检查后重试', 400) from None

    @model_validator(mode='after')
    def validate_plan_schema(self):
        from .module_planning_service import MasterOutput, RegularOutput, RegularModule
        if self.plan.get('creationMode') == 'regular' or self.plan.get('planningContractVersion') == 'regular-design-v1':
            raw = {k:v for k,v in self.plan.items() if k in RegularOutput.model_fields}
            raw['modules'] = [{k:v for k,v in m.items() if k in RegularModule.model_fields} for m in self.plan.get('modules', [])]
            EffectiveRegularOutput.model_validate(raw)
        else:
            MasterOutput.model_validate({k:v for k,v in self.plan.items() if k in MasterOutput.model_fields})
        return self


class BootstrapInput(Wire):
    mode: Literal['hero','suite']
    creationMode: Literal['regular','professional']
    input: ModulePlanInput
    snapshot: EffectiveSnapshot | None = None

class SyncInput(Wire):
    expectedRevision: int = Field(ge=1)
    input: ModulePlanInput
    snapshot: EffectiveSnapshot

class FeedbackInput(SyncInput):
    text: str = Field(min_length=1,max_length=4000)

class ApplyInput(SyncInput):
    candidatePlanId: UUID

class RestoreInput(SyncInput):
    versionId: UUID

class DiscardInput(Wire):
    expectedRevision: int = Field(ge=1)

class SetPlanOperation(Wire):
    kind: Literal['set_plan']
    changes: dict[str, Any]

class SetModuleOperation(Wire):
    kind: Literal['set_module']
    taskId: str = Field(min_length=1,max_length=100)
    changes: dict[str, Any]

class SetParametersOperation(Wire):
    kind: Literal['set_parameters']
    taskId: str = Field(min_length=1,max_length=100)
    parameters: list[dict[str,str]] = Field(max_length=20)

class AddModuleOperation(Wire):
    kind: Literal['add_module']
    module: dict[str, Any]

    @model_validator(mode='after')
    def server_assigns_identity(self):
        if 'taskId' in self.module:
            raise ValueError('New taskId is allocated by the server')
        return self

class DeleteModuleOperation(Wire):
    kind: Literal['delete_module']
    taskId: str = Field(min_length=1,max_length=100)

class ReorderOperation(Wire):
    kind: Literal['reorder']
    taskIds: list[str]

from typing import Annotated
Operation = Annotated[SetPlanOperation | SetModuleOperation | SetParametersOperation | AddModuleOperation | DeleteModuleOperation | ReorderOperation, Field(discriminator='kind')]

class Reply(Wire):
    kind: Literal['answer','clarification','revision']
    message: str = Field(min_length=1,max_length=4000)
    operations: list[Operation] = Field(max_length=100)

    @model_validator(mode='after')
    def operations_match_kind(self):
        if (self.kind == 'revision') != bool(self.operations):
            raise ValueError('revision requires operations; answer and clarification require none')
        return self
