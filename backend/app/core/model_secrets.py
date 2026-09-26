"""模型密钥只在服务端加解密；Windows 使用当前用户 DPAPI。"""
import ctypes
import os
from cryptography.fernet import Fernet, InvalidToken
from .errors import AppError


class ModelSecretCodec:
    def __init__(self, encryption_key=None):
        self._key = encryption_key

    def encrypt(self, value: str) -> bytes:
        if self._key:
            try:
                return b"fernet:" + Fernet(self._key.encode()).encrypt(value.encode())
            except (ValueError, UnicodeError):
                raise AppError("MODEL_SECRET_KEY_INVALID", "后端 MODEL_CONNECTION_ENCRYPTION_KEY 格式无效，请使用 Fernet 密钥", 503) from None
        if os.name == "nt":
            return b"dpapi:" + self._windows(value.encode(), decrypt=False)
        raise AppError("MODEL_SECRET_KEY_REQUIRED", "请在后端配置 MODEL_CONNECTION_ENCRYPTION_KEY 后保存模型连接", 503)

    def decrypt(self, value: bytes) -> str:
        try:
            if value.startswith(b"fernet:") and self._key:
                return Fernet(self._key.encode()).decrypt(value[7:]).decode()
            if value.startswith(b"dpapi:") and os.name == "nt":
                return self._windows(value[6:], decrypt=True).decode()
        except (InvalidToken, ValueError, UnicodeError):
            pass
        raise AppError("MODEL_SECRET_UNAVAILABLE", "模型密钥无法解密，请使用原后端用户运行或重新配置密钥", 503)

    @staticmethod
    def _windows(value, *, decrypt):
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(value)
        source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        target = Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise AppError("MODEL_SECRET_UNAVAILABLE", "当前后端用户无法访问模型密钥", 503)
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            kernel.LocalFree(target.data)
