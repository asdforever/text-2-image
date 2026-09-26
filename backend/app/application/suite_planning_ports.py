from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ..core.errors import AppError


@dataclass(frozen=True)
class PlanningReferenceRequest:
    reference_id: str
    version: str


@dataclass
class PlanningReferenceSnapshot:
    reference_id: str
    version: str
    workspace_id: UUID
    title: str
    source: str
    content_sha256: str
    field_values: dict[str, object]
    active: bool = True

    def to_snapshot(self) -> dict[str, object]:
        return {
            "referenceId": self.reference_id,
            "version": self.version,
            "title": self.title,
            "source": self.source,
            "contentSha256": self.content_sha256,
            "fieldValues": deepcopy(self.field_values),
        }


class PlanningReferenceResolver(Protocol):
    async def resolve(
        self, workspace_id: UUID, references: list[PlanningReferenceRequest]
    ) -> list[PlanningReferenceSnapshot]: ...


class EmptyPlanningReferenceResolver:
    async def resolve(
        self, workspace_id: UUID, references: list[PlanningReferenceRequest]
    ) -> list[PlanningReferenceSnapshot]:
        del workspace_id
        if references:
            raise AppError(
                "PLANNING_REFERENCE_PROVIDER_UNAVAILABLE",
                "当前环境尚未配置规划参考资料服务",
                503,
            )
        return []


class InMemoryPlanningReferenceResolver:
    def __init__(self, snapshots: list[PlanningReferenceSnapshot] | None = None) -> None:
        self._snapshots = {
            (item.workspace_id, item.reference_id, item.version): deepcopy(item)
            for item in snapshots or []
        }

    async def resolve(
        self, workspace_id: UUID, references: list[PlanningReferenceRequest]
    ) -> list[PlanningReferenceSnapshot]:
        keys = [(item.reference_id.strip(), item.version.strip()) for item in references]
        if any(not reference_id or not version for reference_id, version in keys):
            raise AppError("PLANNING_REFERENCE_INVALID", "参考资料标识和版本不能为空", 400)
        if len(keys) != len(set(keys)):
            raise AppError("PLANNING_REFERENCE_INVALID", "参考资料版本不能重复选择", 400)
        resolved: list[PlanningReferenceSnapshot] = []
        for reference_id, version in keys:
            snapshot = self._snapshots.get((workspace_id, reference_id, version))
            if snapshot is None:
                raise AppError("PLANNING_REFERENCE_NOT_FOUND", "规划参考资料版本不存在", 404)
            if not snapshot.active:
                raise AppError("PLANNING_REFERENCE_INACTIVE", "规划参考资料版本已失效", 409)
            resolved.append(deepcopy(snapshot))
        return resolved
