from dataclasses import dataclass
from typing import Any
from uuid import UUID


class ProjectArchiveCoordinator:
    """协调项目生命周期与正式成品档案，隐藏具体持久化实现。"""

    def __init__(self, product_library_service: Any) -> None:
        self.product_library_service = product_library_service

    async def ensure_project_archive(self, project: Any):
        if getattr(project, "status", "active") == "archived":
            existing = await self.product_library_service.get_project_product(
                project.id, include_archived=True
            )
            if existing is not None:
                return existing
        product = await self.product_library_service.ensure_project_product(
            project.id, project.name
        )
        if getattr(project, "status", "active") == "archived":
            product = await self.product_library_service.archive_product(product.id)
        return product

    async def link_project_asset(self, project: Any, asset: Any):
        product = await self.ensure_project_archive(project)
        return await self.product_library_service.link_project_asset(
            product.id, project.id, asset.id
        )

    async def archive_project_output(self, **payload):
        """Delegate a generated output archive to the product library service.

        Generation workers receive this coordinator so project lifecycle and
        output archival share one seam. Keep the output archival contract
        available on the coordinator as well as on the underlying library
        service.
        """
        return await self.product_library_service.archive_project_output(**payload)

    async def unlink_project_asset(
        self, project_id: UUID, project_asset_id: UUID
    ) -> bool:
        product = await self.product_library_service.get_project_product(project_id)
        if product is None:
            return False
        return await self.product_library_service.unlink_project_asset(
            product.id, project_asset_id
        )

    async def archive_project_archive(self, project_id: UUID):
        product = await self.product_library_service.get_project_product(project_id)
        if product is None:
            return None
        return await self.product_library_service.archive_product(product.id)

    async def delete_project_archive(self, project_id: UUID):
        """Hide the project archive when its source project is hard-deleted.

        Product archives are retained as archived records so historical links and
        idempotent cleanup remain safe, while the normal product-library listing
        no longer exposes a project that no longer exists.
        """
        product = await self.product_library_service.get_project_product(project_id)
        if product is None:
            return None
        return await self.product_library_service.archive_product(product.id)


@dataclass
class ProjectArchiveBackfillReport:
    scanned: int = 0
    created: int = 0
    reused: int = 0
    linked: int = 0
    unlinked: int = 0
    failed: int = 0


class ProjectArchiveBackfillService:
    def __init__(
        self,
        project_repository: Any,
        coordinator: ProjectArchiveCoordinator,
        identity_provider: Any,
    ) -> None:
        self.project_repository = project_repository
        self.coordinator = coordinator
        self.identity_provider = identity_provider

    async def backfill_workspace(
        self, *, page_size: int = 100
    ) -> ProjectArchiveBackfillReport:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        workspace_id = self.identity_provider.get_context().workspace_id
        projects = await self.project_repository.list_projects(
            workspace_id, include_archived=True
        )
        report = ProjectArchiveBackfillReport()
        for offset in range(0, len(projects), page_size):
            for project in projects[offset : offset + page_size]:
                report.scanned += 1
                try:
                    existing = await self.coordinator.product_library_service.get_project_product(
                        project.id, include_archived=True
                    )
                    product = await self.coordinator.ensure_project_archive(project)
                    if existing is None:
                        report.created += 1
                    else:
                        report.reused += 1

                    assets = await self.project_repository.list_assets(
                        project.id, workspace_id
                    )
                    asset_ids = {asset.id for asset in assets}
                    links = await self.coordinator.product_library_service.list_product_asset_links(
                        product.id
                    )
                    linked_ids = {link.project_asset_id for link in links}
                    for asset in assets:
                        if asset.id not in linked_ids:
                            await self.coordinator.link_project_asset(project, asset)
                            report.linked += 1
                    for stale_id in linked_ids - asset_ids:
                        if await self.coordinator.unlink_project_asset(project.id, stale_id):
                            report.unlinked += 1
                except Exception:
                    report.failed += 1
        return report
