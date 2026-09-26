from io import BytesIO
from datetime import timedelta
import asyncio
from uuid import UUID

from PIL import Image

from backend.app.project_storage import (
    MemoryProjectAssetStorage,
    MinioProjectAssetStorage,
    inspect_project_image,
    project_asset_object_key,
)
from backend.app.storage import StoredObject
from backend.app.storage_minio import MinioObjectStorage


def _png() -> bytes:
    image = Image.new("RGB", (16, 9), "red")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_project_storage_key_is_server_scoped_and_filename_independent() -> None:
    key = project_asset_object_key(
        UUID(int=1), UUID(int=2), UUID(int=3), "image/png"
    )

    assert key == "projects/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002/00000000-0000-0000-0000-000000000003/original.png"


def test_project_storage_validates_image_and_reads_written_object() -> None:
    mime_type, width, height, digest = inspect_project_image(_png(), "image/png", 1024)
    storage = MemoryProjectAssetStorage()
    key = project_asset_object_key(UUID(int=1), UUID(int=2), UUID(int=3), mime_type)

    import asyncio

    asyncio.run(storage.put(StoredObject(key, _png(), mime_type)))
    stored = asyncio.run(storage.get(key))

    assert (mime_type, width, height, len(digest)) == ("image/png", 16, 9, 64)
    assert stored is not None
    assert stored.data == _png()


class _RecordingMinioClient:
    """只记录参数、不做网络调用，并复刻 minio 对 expires 的类型校验。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def presigned_get_object(self, bucket: str, key: str, expires=None, **kwargs) -> str:
        self.calls.append((bucket, key, expires))
        # minio 内部会调用 expires.total_seconds()；传 int 时这里就会抛
        # AttributeError: 'int' object has no attribute 'total_seconds'
        expires.total_seconds()
        return f"https://example.test/{bucket}/{key}"


def test_minio_preview_url_passes_timedelta_expiry() -> None:
    client = _RecordingMinioClient()
    storage = MinioObjectStorage(client, "picagent", expiry_seconds=300)

    url = asyncio.run(storage.preview_url("image-edit/a/b/c.png"))

    assert url.endswith("image-edit/a/b/c.png")
    bucket, key, expires = client.calls[0]
    assert (bucket, key) == ("picagent", "image-edit/a/b/c.png")
    assert isinstance(expires, timedelta)
    assert expires.total_seconds() == 300


def test_project_asset_minio_preview_url_passes_timedelta_expiry() -> None:
    """回归：白底图生成走的是 MinioProjectAssetStorage，同样必须传 timedelta。

    传 int 会让 presigned_get_object 抛 AttributeError，worker 会把它记成
    任务失败，导致已经生成并上传的图片被丢弃、白底图工作区看不到结果。
    """
    client = _RecordingMinioClient()
    storage = MinioProjectAssetStorage(client, "picagent")

    asyncio.run(storage.preview_url("image-edit/a/b/c.png"))

    assert isinstance(client.calls[0][2], timedelta)
