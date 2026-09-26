"""MinIO 工具函数，用于素材库和测试产物的文件管理"""
import asyncio
import io
import logging
from datetime import timedelta
from uuid import UUID

from minio import Minio
from PIL import Image


logger = logging.getLogger("picagent.storage")


# 图片处理配置
MAX_INPUT_SIZE = (4096, 4096)  # 输入图片最大尺寸
MAX_FILE_SIZE_MB = 10  # 输入图片最大文件大小(MB)
OUTPUT_MAX_SIZE = (2048, 2048)  # 输出图片最大尺寸
OUTPUT_MIN_SIZE = (512, 512)  # 输出图片最小尺寸
OUTPUT_MAX_FILE_SIZE_MB = 20  # 输出图片最大文件大小(MB)


def preprocess_image(file_data: bytes, max_size: tuple[int, int] = MAX_INPUT_SIZE) -> bytes:
    """
    预处理输入图片：
    - 压缩过大的图片
    - 清理 EXIF 信息
    - 统一格式为 JPEG/PNG

    Returns:
        处理后的图片数据
    """
    img = Image.open(io.BytesIO(file_data))

    # 保留原始格式（PNG保留透明度，其他转JPEG）
    output_format = "PNG" if img.mode in ("RGBA", "LA", "P") else "JPEG"

    # 如果图片过大，等比例缩放
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    # 清除 EXIF 信息并保存
    output = io.BytesIO()
    if output_format == "JPEG":
        # 转换为RGB模式（JPEG不支持透明度）
        if img.mode in ("RGBA", "LA", "P"):
            # 创建白色背景
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        img.save(output, format="JPEG", quality=85, optimize=True)
    else:
        img.save(output, format="PNG", optimize=True)

    return output.getvalue()


def validate_output_image(file_data: bytes) -> tuple[bool, str]:
    """
    验证输出图片规格：
    - 检查分辨率是否在范围内
    - 检查文件大小是否合理

    Returns:
        (是否有效, 错误信息)
    """
    try:
        img = Image.open(io.BytesIO(file_data))
        width, height = img.size
        file_size_mb = len(file_data) / (1024 * 1024)

        if width < OUTPUT_MIN_SIZE[0] or height < OUTPUT_MIN_SIZE[1]:
            return False, f"图片尺寸过小: {width}x{height}，最小要求 {OUTPUT_MIN_SIZE[0]}x{OUTPUT_MIN_SIZE[1]}"

        if width > OUTPUT_MAX_SIZE[0] or height > OUTPUT_MAX_SIZE[1]:
            return False, f"图片尺寸过大: {width}x{height}，最大限制 {OUTPUT_MAX_SIZE[0]}x{OUTPUT_MAX_SIZE[1]}"

        if file_size_mb > OUTPUT_MAX_FILE_SIZE_MB:
            return False, f"文件大小过大: {file_size_mb:.2f}MB，最大限制 {OUTPUT_MAX_FILE_SIZE_MB}MB"

        return True, ""
    except Exception:
        return False, "图片验证失败"


class AssetStoragePort:
    """素材存储端口定义"""

    async def ensure_bucket_exists(self) -> None:
        raise NotImplementedError

    async def upload_asset_image(
        self,
        library_id: UUID,
        asset_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int, int, int]:
        raise NotImplementedError

    async def upload_test_result(
        self,
        test_run_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int]:
        raise NotImplementedError

    async def upload_product(
        self,
        library_id: str,
        product_id: str,
        file_data: bytes,
        filename: str,
        content_type: str,
        test_run_id: str | None = None,
    ) -> tuple[str, str, str, int]:
        raise NotImplementedError

    async def generate_presigned_url(self, key: str, expiry_seconds: int = 3600) -> str:
        raise NotImplementedError

    async def delete_file(self, key: str) -> None:
        raise NotImplementedError

    async def delete_directory(self, prefix: str) -> None:
        raise NotImplementedError


class MemoryAssetStorage(AssetStoragePort):
    """内存版本的素材存储（用于测试和开发）"""

    def __init__(self):
        self._storage: dict[str, bytes] = {}

    async def ensure_bucket_exists(self) -> None:
        pass

    async def upload_asset_image(
        self,
        library_id: UUID,
        asset_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int, int, int]:
        processed_data = preprocess_image(file_data, MAX_INPUT_SIZE)
        img = Image.open(io.BytesIO(processed_data))
        width, height = img.size
        ext = "png" if img.format == "PNG" else "jpg"
        file_type = f"image/{ext}"
        key = f"test-assets/images/{library_id}/{asset_id}.{ext}"
        self._storage[key] = processed_data
        return "memory", key, file_type, len(processed_data), width, height

    async def upload_test_result(
        self,
        test_run_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int]:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
        key = f"test-results/{test_run_id}/output.{ext}"
        if ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            file_type = f"image/{ext}"
        elif ext in ["mp4", "avi", "mov"]:
            file_type = f"video/{ext}"
        else:
            file_type = "application/octet-stream"
        self._storage[key] = file_data
        return "memory", key, file_type, len(file_data)

    async def upload_product(
        self,
        library_id: str,
        product_id: str,
        file_data: bytes,
        filename: str,
        content_type: str,
        test_run_id: str | None = None,
    ) -> tuple[str, str, str, int]:
        if test_run_id:
            return await self.upload_test_result(UUID(test_run_id), file_data, filename)
        suffix = f".{filename.rsplit('.', 1)[-1]}" if "." in filename else ""
        key = f"products/{library_id}/{product_id}{suffix}"
        self._storage[key] = file_data
        return "memory", key, content_type, len(file_data)

    async def generate_presigned_url(self, key: str, expiry_seconds: int = 3600) -> str:
        return f"memory://{key}"

    async def delete_file(self, key: str) -> None:
        self._storage.pop(key, None)

    async def delete_directory(self, prefix: str) -> None:
        keys_to_delete = [k for k in self._storage if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._storage[k]


class AssetMinioStorage(AssetStoragePort):
    """素材和产物的 MinIO 存储工具"""

    def __init__(self, client: Minio, bucket: str = "suite-workbench"):
        self.client = client
        self.bucket = bucket

    async def ensure_bucket_exists(self) -> None:
        """确保 MinIO 桶存在，不存在则创建"""
        def _check_and_create():
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                return True
            return False

        created = await asyncio.to_thread(_check_and_create)
        logger.info(
            "object storage bucket initialized"
            if created
            else "object storage bucket is ready"
        )

    async def upload_asset_image(
        self,
        library_id: UUID,
        asset_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int, int, int]:
        """
        上传图片素材到 MinIO（带预处理）

        Returns:
            (bucket, key, file_type, file_size, width, height)
        """
        # 检查文件大小
        file_size_mb = len(file_data) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(f"文件大小超过限制: {file_size_mb:.2f}MB，最大 {MAX_FILE_SIZE_MB}MB")

        # 预处理图片：压缩、清理EXIF
        try:
            processed_data = preprocess_image(file_data, MAX_INPUT_SIZE)
        except Exception as exc:
            raise ValueError("图片预处理失败") from exc

        # 检测图片尺寸
        try:
            img = Image.open(io.BytesIO(processed_data))
            width, height = img.size
            # 根据实际格式确定扩展名
            ext = "png" if img.format == "PNG" else "jpg"
            file_type = f"image/{ext}"
        except Exception as exc:
            raise ValueError("无法读取图片") from exc

        # 构造 MinIO 路径
        key = f"test-assets/images/{library_id}/{asset_id}.{ext}"
        file_size = len(processed_data)

        # 上传到 MinIO
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            key,
            io.BytesIO(processed_data),
            file_size,
            content_type=file_type,
        )

        return self.bucket, key, file_type, file_size, width, height

    async def upload_test_result(
        self,
        test_run_id: UUID,
        file_data: bytes,
        filename: str,
    ) -> tuple[str, str, str, int]:
        """
        上传测试产物到 MinIO

        Returns:
            (bucket, key, file_type, file_size)
        """
        # 提取文件扩展名
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"

        # 构造 MinIO 路径
        key = f"test-results/{test_run_id}/output.{ext}"

        # 检测文件类型
        if ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            file_type = f"image/{ext}"
        elif ext in ["mp4", "avi", "mov"]:
            file_type = f"video/{ext}"
        else:
            file_type = "application/octet-stream"

        file_size = len(file_data)

        # 上传到 MinIO
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            key,
            io.BytesIO(file_data),
            file_size,
            content_type=file_type,
        )

        return self.bucket, key, file_type, file_size

    async def upload_product(
        self,
        library_id: str,
        product_id: str,
        file_data: bytes,
        filename: str,
        content_type: str,
        test_run_id: str | None = None,
    ) -> tuple[str, str, str, int]:
        """通过统一存储边界上传手工产物或测试产物。"""
        if test_run_id:
            return await self.upload_test_result(
                test_run_id, file_data, filename
            )

        suffix = f".{filename.rsplit('.', 1)[-1]}" if "." in filename else ""
        key = f"products/{library_id}/{product_id}{suffix}"
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            key,
            io.BytesIO(file_data),
            len(file_data),
            content_type=content_type,
        )
        return self.bucket, key, content_type, len(file_data)

    async def generate_presigned_url(self, key: str, expiry_seconds: int = 3600) -> str:
        """
        生成预签名 URL（默认 1 小时有效期）

        Args:
            key: MinIO 对象 key
            expiry_seconds: 有效期（秒）

        Returns:
            预签名 URL
        """
        return await asyncio.to_thread(
            self.client.presigned_get_object,
            self.bucket,
            key,
            expires=timedelta(seconds=expiry_seconds),
        )

    async def delete_file(self, key: str) -> None:
        """删除 MinIO 中的文件"""
        await asyncio.to_thread(self.client.remove_object, self.bucket, key)

    async def download_file(self, key: str) -> bytes:
        """从 MinIO 下载文件内容

        Args:
            key: MinIO 对象 key

        Returns:
            文件内容（字节）
        """
        def _download():
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_download)

    async def delete_directory(self, prefix: str) -> None:
        """删除 MinIO 中指定前缀的所有文件"""
        def _delete_all():
            objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
            for obj in objects:
                self.client.remove_object(self.bucket, obj.object_name)

        await asyncio.to_thread(_delete_all)
