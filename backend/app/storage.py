from dataclasses import dataclass


@dataclass
class StoredObject:
    key: str
    data: bytes
    content_type: str


class ObjectStorage:
    async def put(self, obj: StoredObject) -> None: raise NotImplementedError
    async def get(self, key: str) -> StoredObject | None: raise NotImplementedError
    async def delete(self, key: str) -> None: raise NotImplementedError
    async def preview_url(self, key: str) -> str: raise NotImplementedError
    async def ready(self) -> bool: return True


class MemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    async def put(self, obj: StoredObject) -> None: self.objects[obj.key] = obj
    async def get(self, key: str) -> StoredObject | None: return self.objects.get(key)
    async def delete(self, key: str) -> None: self.objects.pop(key, None)
    async def preview_url(self, key: str) -> str: return f"/api/storage/{key}"
    async def ready(self) -> bool: return True
