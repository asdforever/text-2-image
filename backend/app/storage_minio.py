import asyncio
from datetime import timedelta

from minio import Minio

from .storage import ObjectStorage, StoredObject


class MinioObjectStorage(ObjectStorage):
    def __init__(self, client: Minio, bucket: str, expiry_seconds: int = 300) -> None:
        self.client = client
        self.bucket = bucket
        self.expiry_seconds = expiry_seconds

    async def put(self, obj: StoredObject) -> None:
        await asyncio.to_thread(self.client.put_object, self.bucket, obj.key, __import__("io").BytesIO(obj.data), len(obj.data), content_type=obj.content_type)

    async def get(self, key: str) -> StoredObject | None:
        def read() -> StoredObject | None:
            try:
                response = self.client.get_object(self.bucket, key)
                try:
                    return StoredObject(key, response.read(), response.headers.get("Content-Type", "application/octet-stream"))
                finally:
                    response.close(); response.release_conn()
            except Exception as exc:
                if "NoSuchKey" in str(exc) or "not exist" in str(exc).lower(): return None
                raise
        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.bucket, key)

    async def preview_url(self, key: str) -> str:
        # minio 的 expires 参数要求 datetime.timedelta；直接传 int 会在
        # presigned_get_object 内部抛 AttributeError: 'int' object has no
        # attribute 'total_seconds'，导致生成结果被丢弃。
        return await asyncio.to_thread(
            self.client.presigned_get_object,
            self.bucket,
            key,
            timedelta(seconds=self.expiry_seconds),
        )

    async def ready(self) -> bool:
        try:
            return await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        except Exception:
            return False
