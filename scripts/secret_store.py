from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _local_free(pointer: object) -> None:
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    kernel32.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("安全记住密钥目前仅支持Windows")
    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(b"yantu-editor-v1")
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob), "研途编辑模型密钥", ctypes.byref(entropy_blob),
        None, None, 0, ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(output_blob.pbData)
        del input_buffer, entropy_buffer


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("安全记住密钥目前仅支持Windows")
    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(b"yantu-editor-v1")
    output_blob = DataBlob()
    description = wintypes.LPWSTR()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), ctypes.byref(description), ctypes.byref(entropy_blob),
        None, None, 0, ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(output_blob.pbData)
        if description:
            _local_free(description)
        del input_buffer, entropy_buffer


def save_credentials(path: Path, api_key: str, base_url: str, model: str) -> None:
    plaintext = json.dumps(
        {"api_key": api_key, "base_url": base_url, "model": model},
        ensure_ascii=False,
    ).encode("utf-8")
    envelope = {
        "version": 1,
        "protection": "windows_dpapi_current_user",
        "ciphertext": base64.b64encode(_protect(plaintext)).decode("ascii"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_credentials(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("protection") != "windows_dpapi_current_user":
        raise ValueError("未知的密钥保护方式")
    plaintext = _unprotect(base64.b64decode(envelope["ciphertext"]))
    payload = json.loads(plaintext.decode("utf-8"))
    required = {"api_key", "base_url", "model"}
    if not required.issubset(payload):
        raise ValueError("加密配置缺少必要字段")
    return {item: str(payload[item]) for item in required}


def forget_credentials(path: Path) -> None:
    if path.exists():
        path.unlink()

