"""素材库、产物库和提示词测试运行的应用边界。"""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from ..models.asset import Asset, AssetLibrary, TestProduct, TestProductLibrary, TestRun
from ..models.prompt import PromptVersion


def _uuid(value: str, message: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=message) from exc


def _metadata(value: Any) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON in metadata") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON in metadata")
    return parsed


def _library_view(library: AssetLibrary) -> dict:
    return {
        "id": str(library.id),
        "name": library.name,
        "description": library.description,
        "assetType": library.asset_type,
        "createdAt": library.created_at.isoformat(),
        "updatedAt": library.updated_at.isoformat(),
    }


async def _safe_url(storage: Any, key: str | None) -> str | None:
    if storage is None or not key:
        return None
    try:
        return await storage.generate_presigned_url(key)
    except Exception:
        return None


async def _asset_view(asset: Asset, storage: Any) -> dict:
    data = {
        "id": str(asset.id),
        "libraryId": str(asset.library_id),
        "name": asset.name,
        "assetType": asset.asset_type,
        "createdAt": asset.created_at.isoformat(),
    }
    if asset.asset_type == "image":
        data.update(
            {
                "minioBucket": asset.minio_bucket,
                "minioKey": asset.minio_key,
                "fileType": asset.file_type,
                "fileSize": asset.file_size,
                "width": asset.width,
                "height": asset.height,
            }
        )
        url = await _safe_url(storage, asset.minio_key)
        if url:
            data["url"] = url
    else:
        data["content"] = asset.content
    if asset.extra_metadata:
        data["metadata"] = asset.extra_metadata
    return data


class SqlAlchemyAssetService:
    def __init__(self, session_factory, storage=None) -> None:
        self.session_factory = session_factory
        self.storage = storage

    async def list_libraries(self) -> list[dict]:
        async with self.session_factory() as db:
            result = await db.execute(
                select(AssetLibrary).order_by(AssetLibrary.created_at.desc())
            )
            return [_library_view(item) for item in result.scalars().all()]

    async def create_library(self, payload: dict) -> dict:
        name = payload.get("name")
        asset_type = payload.get("assetType")
        if not name or not asset_type:
            raise HTTPException(status_code=400, detail="name and assetType are required")
        if asset_type not in {"image", "text"}:
            raise HTTPException(
                status_code=400, detail="assetType must be 'image' or 'text'"
            )
        async with self.session_factory() as db:
            library = AssetLibrary(
                name=name,
                description=payload.get("description", ""),
                asset_type=asset_type,
            )
            db.add(library)
            await db.commit()
            await db.refresh(library)
            return _library_view(library)

    async def get_library(self, library_id: str) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(AssetLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Asset library not found")
            return _library_view(library)

    async def update_library(self, library_id: str, payload: dict) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(AssetLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Asset library not found")
            if "name" in payload:
                library.name = payload["name"]
            if "description" in payload:
                library.description = payload["description"]
            await db.commit()
            await db.refresh(library)
            return _library_view(library)

    async def delete_library(self, library_id: str) -> None:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(AssetLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Asset library not found")
            if self.storage and library.asset_type == "image":
                await self.storage.delete_directory(
                    f"test-assets/images/{library_id}/"
                )
            await db.delete(library)
            await db.commit()

    async def list_assets(self, library_id: str) -> list[dict]:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            if await db.get(AssetLibrary, library_uuid) is None:
                raise HTTPException(status_code=404, detail="Asset library not found")
            result = await db.execute(
                select(Asset)
                .where(Asset.library_id == library_uuid)
                .order_by(Asset.created_at.desc())
            )
            return [
                await _asset_view(item, self.storage)
                for item in result.scalars().all()
            ]

    async def create_asset(self, library_id: str, payload: dict) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(AssetLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Asset library not found")
            if not payload.get("name"):
                raise HTTPException(status_code=400, detail="name is required")

            asset = Asset(
                library_id=library_uuid,
                name=payload["name"],
                asset_type=library.asset_type,
                extra_metadata=_metadata(payload.get("metadata")),
            )
            if library.asset_type == "image":
                if payload.get("fileData") is None:
                    raise HTTPException(
                        status_code=400, detail="file is required for image assets"
                    )
                if self.storage is None:
                    raise HTTPException(status_code=500, detail="Storage not configured")
                db.add(asset)
                await db.flush()
                try:
                    values = await self.storage.upload_asset_image(
                        str(library.id),
                        str(asset.id),
                        payload["fileData"],
                        payload.get("filename") or "upload",
                    )
                except Exception as exc:
                    await db.rollback()
                    raise HTTPException(
                        status_code=500, detail="Asset storage is unavailable"
                    ) from exc
                (
                    asset.minio_bucket,
                    asset.minio_key,
                    asset.file_type,
                    asset.file_size,
                    asset.width,
                    asset.height,
                ) = values
            else:
                if not payload.get("content"):
                    raise HTTPException(
                        status_code=400, detail="content is required for text assets"
                    )
                asset.content = payload["content"]
                db.add(asset)

            await db.commit()
            await db.refresh(asset)
            return await _asset_view(asset, self.storage)

    async def delete_asset(self, library_id: str, asset_id: str) -> None:
        library_uuid = _uuid(library_id, "Invalid ID format")
        asset_uuid = _uuid(asset_id, "Invalid ID format")
        async with self.session_factory() as db:
            asset = await db.get(Asset, asset_uuid)
            if asset is None or asset.library_id != library_uuid:
                raise HTTPException(status_code=404, detail="Asset not found")
            if self.storage and asset.asset_type == "image" and asset.minio_key:
                try:
                    await self.storage.delete_file(asset.minio_key)
                except Exception:
                    pass
            await db.delete(asset)
            await db.commit()


def _product_library_view(library: TestProductLibrary) -> dict:
    return {
        "id": str(library.id),
        "name": library.name,
        "description": library.description,
        "libraryType": library.library_type,
        "createdAt": library.created_at.isoformat(),
        "updatedAt": library.updated_at.isoformat(),
    }


async def _product_view(product: TestProduct, storage: Any) -> dict:
    data = {
        "id": str(product.id),
        "libraryId": str(product.library_id),
        "name": product.name,
        "productType": product.product_type,
        "minioBucket": product.minio_bucket,
        "minioKey": product.minio_key,
        "fileType": product.file_type,
        "fileSize": product.file_size,
        "createdAt": product.created_at.isoformat(),
        "updatedAt": getattr(product, "updated_at", product.created_at).isoformat(),
    }
    if product.test_run_id:
        data["testRunId"] = str(product.test_run_id)
    if product.project_id:
        data["projectId"] = str(product.project_id)
    if product.extra_metadata:
        data["metadata"] = product.extra_metadata
    url = await _safe_url(storage, product.minio_key)
    if url:
        data["url"] = url
    return data


class SqlAlchemyProductService:
    def __init__(self, session_factory, storage=None) -> None:
        self.session_factory = session_factory
        self.storage = storage

    async def list_libraries(self) -> list[dict]:
        async with self.session_factory() as db:
            result = await db.execute(
                select(TestProductLibrary).order_by(TestProductLibrary.created_at.desc())
            )
            return [_product_library_view(item) for item in result.scalars().all()]

    async def create_library(self, payload: dict) -> dict:
        name = payload.get("name")
        library_type = payload.get("libraryType")
        if not name or not library_type:
            raise HTTPException(
                status_code=400, detail="name and libraryType are required"
            )
        if library_type not in {"test_result", "manual"}:
            raise HTTPException(
                status_code=400,
                detail="libraryType must be 'test_result' or 'manual'",
            )
        async with self.session_factory() as db:
            library = TestProductLibrary(
                name=name,
                description=payload.get("description", ""),
                library_type=library_type,
            )
            db.add(library)
            await db.commit()
            await db.refresh(library)
            return _product_library_view(library)

    async def get_library(self, library_id: str) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(TestProductLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Product library not found")
            return _product_library_view(library)

    async def update_library(self, library_id: str, payload: dict) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(TestProductLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Product library not found")
            if "name" in payload:
                library.name = payload["name"]
            if "description" in payload:
                library.description = payload["description"]
            await db.commit()
            await db.refresh(library)
            return _product_library_view(library)

    async def delete_library(self, library_id: str) -> None:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            library = await db.get(TestProductLibrary, library_uuid)
            if library is None:
                raise HTTPException(status_code=404, detail="Product library not found")
            result = await db.execute(
                select(TestProduct).where(TestProduct.library_id == library_uuid)
            )
            if self.storage:
                for product in result.scalars().all():
                    if product.minio_key:
                        try:
                            await self.storage.delete_file(product.minio_key)
                        except Exception:
                            pass
            await db.delete(library)
            await db.commit()

    async def list_products(self, library_id: str) -> list[dict]:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        async with self.session_factory() as db:
            if await db.get(ProductLibrary, library_uuid) is None:
                raise HTTPException(status_code=404, detail="Product library not found")
            result = await db.execute(
                select(Product)
                .where(Product.library_id == library_uuid)
                .order_by(TestProduct.created_at.desc())
            )
            return [
                await _product_view(item, self.storage)
                for item in result.scalars().all()
            ]

    async def create_product(self, library_id: str, payload: dict) -> dict:
        library_uuid = _uuid(library_id, "Invalid library ID format")
        name = payload.get("name")
        product_type = payload.get("productType")
        if not name or not product_type or payload.get("fileData") is None:
            raise HTTPException(
                status_code=400,
                detail="name, productType, and file are required",
            )
        if product_type not in {"image", "video", "audio", "document"}:
            raise HTTPException(status_code=400, detail="Invalid productType")
        if self.storage is None:
            raise HTTPException(status_code=500, detail="Storage not configured")

        async with self.session_factory() as db:
            if await db.get(ProductLibrary, library_uuid) is None:
                raise HTTPException(status_code=404, detail="Product library not found")
            product = TestProduct(
                library_id=library_uuid,
                name=name,
                product_type=product_type,
                extra_metadata=_metadata(payload.get("metadata")),
            )
            if payload.get("testRunId"):
                product.test_run_id = _uuid(
                    payload["testRunId"], "Invalid testRunId format"
                )
            if payload.get("projectId"):
                product.project_id = _uuid(
                    payload["projectId"], "Invalid projectId format"
                )
            db.add(product)
            await db.flush()
            try:
                values = await self.storage.upload_product(
                    str(library_uuid),
                    str(product.id),
                    payload["fileData"],
                    payload.get("filename") or "upload",
                    payload.get("contentType") or "application/octet-stream",
                    str(product.test_run_id) if product.test_run_id else None,
                )
            except Exception as exc:
                await db.rollback()
                raise HTTPException(
                    status_code=500, detail="Product storage is unavailable"
                ) from exc
            (
                product.minio_bucket,
                product.minio_key,
                product.file_type,
                product.file_size,
            ) = values
            await db.commit()
            await db.refresh(product)
            return await _product_view(product, self.storage)

    async def delete_product(self, library_id: str, product_id: str) -> None:
        library_uuid = _uuid(library_id, "Invalid ID format")
        product_uuid = _uuid(product_id, "Invalid ID format")
        async with self.session_factory() as db:
            product = await db.get(TestProduct, product_uuid)
            if product is None or product.library_id != library_uuid:
                raise HTTPException(status_code=404, detail="Product not found")
            if self.storage and product.minio_key:
                try:
                    await self.storage.delete_file(product.minio_key)
                except Exception:
                    pass
            await db.delete(product)
            await db.commit()


def _test_run_view(test_run: TestRun) -> dict:
    data = {
        "id": str(test_run.id),
        "promptVersionId": str(test_run.prompt_version_id),
        "status": test_run.status,
        "createdAt": test_run.created_at.isoformat(),
    }
    if test_run.input_asset_id:
        data["inputAssetId"] = str(test_run.input_asset_id)
    if test_run.input_text:
        data["inputText"] = test_run.input_text
    if test_run.output_product_id:
        data["outputProductId"] = str(test_run.output_product_id)
    if test_run.output_text:
        data["outputText"] = test_run.output_text
    if test_run.duration_ms is not None:
        data["durationMs"] = test_run.duration_ms
    if test_run.error_message:
        data["errorMessage"] = test_run.error_message
    return data


class SqlAlchemyTestRunService:
    def __init__(self, session_factory, storage=None, executor=None) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.executor = executor
        self.model_connections = None

    async def list_runs(self, prompt_version_id: str | None = None) -> list[dict]:
        async with self.session_factory() as db:
            query = select(TestRun).order_by(TestRun.created_at.desc())
            if prompt_version_id:
                version_uuid = _uuid(
                    prompt_version_id, "Invalid prompt_version_id format"
                )
                query = query.where(TestRun.prompt_version_id == version_uuid)
            result = await db.execute(query)
            return [_test_run_view(item) for item in result.scalars().all()]

    async def create_run(self, payload: dict) -> dict:
        if not payload.get("promptVersionId"):
            raise HTTPException(status_code=400, detail="promptVersionId is required")
        version_uuid = _uuid(
            payload["promptVersionId"], "Invalid promptVersionId format"
        )
        if not payload.get("inputAssetId") and not payload.get("inputText"):
            raise HTTPException(
                status_code=400,
                detail="Either inputAssetId or inputText is required",
            )
        from .model_connection_service import model_selection_id
        connection = await self.model_connections.snapshot(model_selection_id(payload.get("modelId"))) if self.model_connections else None
        async with self.session_factory() as db:
            version = await db.get(PromptVersion, version_uuid)
            if version is None:
                raise HTTPException(status_code=404, detail="Prompt version not found")
            from .prompt_usage import require_image_prompt
            require_image_prompt(version)
            asset_uuid = None
            if payload.get("inputAssetId"):
                asset_uuid = _uuid(
                    payload["inputAssetId"], "Invalid inputAssetId format"
                )
                if await db.get(Asset, asset_uuid) is None:
                    raise HTTPException(status_code=404, detail="Input asset not found")
            test_run = TestRun(
                prompt_version_id=version_uuid,
                input_asset_id=asset_uuid,
                input_text=payload.get("inputText"),
                request_snapshot={
                    "inputAssetId": str(asset_uuid) if asset_uuid else None,
                    "inputText": payload.get("inputText"),
                    "generationParams": dict(payload.get("generationParams") or {}),
                    "model": connection["modelName"] if connection else getattr(self.executor, "model", None),
                    **({"modelConnection":connection} if connection else {}),
                },
                status="pending",
            )
            db.add(test_run)
            await db.commit()
            await db.refresh(test_run)
            data = _test_run_view(test_run)
            data.setdefault("inputAssetId", None)
            data.setdefault("inputText", None)
            if self.executor is not None:
                asyncio.create_task(self.executor.execute(test_run.id))
            return data

    async def get_run(self, test_run_id: str) -> dict:
        run_uuid = _uuid(test_run_id, "Invalid test_run_id format")
        async with self.session_factory() as db:
            test_run = await db.get(TestRun, run_uuid)
            if test_run is None:
                raise HTTPException(status_code=404, detail="Test run not found")
            data = _test_run_view(test_run)
            if test_run.input_asset_id:
                asset = await db.get(Asset, test_run.input_asset_id)
                if asset:
                    asset_data = {
                        "id": str(asset.id),
                        "name": asset.name,
                        "assetType": asset.asset_type,
                    }
                    if asset.asset_type == "image":
                        url = await _safe_url(self.storage, asset.minio_key)
                        if url:
                            asset_data["url"] = url
                    else:
                        asset_data["content"] = asset.content
                    data["inputAsset"] = asset_data
            if test_run.output_product_id:
                product = await db.get(TestProduct, test_run.output_product_id)
                if product:
                    product_data = {
                        "id": str(product.id),
                        "name": product.name,
                        "productType": product.product_type,
                        "fileSize": product.file_size,
                    }
                    url = await _safe_url(self.storage, product.minio_key)
                    if url:
                        product_data["url"] = url
                    data["outputProduct"] = product_data
            return data

    async def update_run(self, test_run_id: str, payload: dict) -> dict:
        run_uuid = _uuid(test_run_id, "Invalid test_run_id format")
        async with self.session_factory() as db:
            test_run = await db.get(TestRun, run_uuid)
            if test_run is None:
                raise HTTPException(status_code=404, detail="Test run not found")
            if "status" in payload:
                if payload["status"] not in {"pending", "running", "completed", "failed"}:
                    raise HTTPException(status_code=400, detail="Invalid status")
                test_run.status = payload["status"]
            if "outputProductId" in payload:
                product_uuid = _uuid(
                    payload["outputProductId"], "Invalid outputProductId format"
                )
                if await db.get(Product, product_uuid) is None:
                    raise HTTPException(status_code=404, detail="Output product not found")
                test_run.output_product_id = product_uuid
            if "outputText" in payload:
                test_run.output_text = payload["outputText"]
            if "durationMs" in payload:
                test_run.duration_ms = int(payload["durationMs"])
            if "errorMessage" in payload:
                test_run.error_message = payload["errorMessage"]
            await db.commit()
            await db.refresh(test_run)
            return _test_run_view(test_run)

    async def delete_run(self, test_run_id: str) -> None:
        run_uuid = _uuid(test_run_id, "Invalid test_run_id format")
        async with self.session_factory() as db:
            test_run = await db.get(TestRun, run_uuid)
            if test_run is None:
                raise HTTPException(status_code=404, detail="Test run not found")
            if test_run.output_product_id:
                product = await db.get(TestProduct, test_run.output_product_id)
                if product:
                    if self.storage and product.minio_key:
                        try:
                            await self.storage.delete_file(product.minio_key)
                        except Exception:
                            pass
                    await db.delete(product)
            await db.delete(test_run)
            await db.commit()
