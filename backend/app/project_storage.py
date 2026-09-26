from uuid import UUID

from minio import Minio

from .image_processing import inspect_image
from .storage import MemoryObjectStorage, ObjectStorage
from .storage_minio import MinioObjectStorage


_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def project_asset_object_key(
    workspace_id: UUID, project_id: UUID, asset_id: UUID, media_type: str
) -> str:
    extension = _EXTENSIONS.get(media_type)
    if extension is None:
        raise ValueError("unsupported project asset media type")
    return f"projects/{workspace_id}/{project_id}/{asset_id}/original.{extension}"


def inspect_project_image(
    body: bytes, declared_mime: str | None, max_upload_bytes: int
) -> tuple[str, int, int, str]:
    return inspect_image(body, declared_mime, max_upload_bytes)


class ProjectAssetStoragePort(ObjectStorage):
    """项目资产对象存储端口，复用通用读写和就绪语义。"""


class MemoryProjectAssetStorage(MemoryObjectStorage, ProjectAssetStoragePort):
    pass


class MinioProjectAssetStorage(MinioObjectStorage, ProjectAssetStoragePort):
    def __init__(self, client: Minio, bucket: str, expiry_seconds: int = 300) -> None:
        super().__init__(client, bucket, expiry_seconds)
