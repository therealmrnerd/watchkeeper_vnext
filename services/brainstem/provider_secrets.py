from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from typing import Any, Protocol


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER_SECRETS_PATH = Path(
    os.getenv("WKV_PROVIDER_SECRETS_PATH", ROOT_DIR / "data" / "secure" / "provider_secrets.dpapi")
)


class SecretCodec(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDpapiCodec:
    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows DPAPI is only available on Windows")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _make_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_ubyte] | None]:
        raw = bytes(data or b"")
        if not raw:
            return _DataBlob(0, None), None
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        return _DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf

    def _blob_bytes(self, blob: _DataBlob) -> bytes:
        if not blob.cbData or not blob.pbData:
            return b""
        return ctypes.string_at(blob.pbData, blob.cbData)

    def encrypt(self, plaintext: bytes) -> bytes:
        in_blob, _ = self._make_blob(plaintext)
        out_blob = _DataBlob()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "Watchkeeper Provider Secrets",
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return self._blob_bytes(out_blob)
        finally:
            if out_blob.pbData:
                self._kernel32.LocalFree(out_blob.pbData)

    def decrypt(self, ciphertext: bytes) -> bytes:
        in_blob, _ = self._make_blob(ciphertext)
        out_blob = _DataBlob()
        description = ctypes.c_wchar_p()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return self._blob_bytes(out_blob)
        finally:
            if out_blob.pbData:
                self._kernel32.LocalFree(out_blob.pbData)
            if description:
                self._kernel32.LocalFree(description)


def _default_payload() -> dict[str, Any]:
    return {"schema_version": "1.0", "providers": {}}


def _normalize_store(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _default_payload()
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    return {
        "schema_version": "1.0",
        "providers": providers,
    }


def load_provider_secret_store(
    path: str | Path | None = None,
    *,
    codec: SecretCodec | None = None,
) -> dict[str, Any]:
    secret_path = Path(path) if path is not None else DEFAULT_PROVIDER_SECRETS_PATH
    if not secret_path.exists():
        return _default_payload()
    raw = secret_path.read_bytes()
    if not raw:
        return _default_payload()
    active_codec = codec or WindowsDpapiCodec()
    try:
        plaintext = active_codec.decrypt(raw)
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"provider secrets file is unreadable: {secret_path}") from exc
    return _normalize_store(payload)


def save_provider_secret_store(
    payload: dict[str, Any],
    path: str | Path | None = None,
    *,
    codec: SecretCodec | None = None,
) -> Path:
    secret_path = Path(path) if path is not None else DEFAULT_PROVIDER_SECRETS_PATH
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    active_codec = codec or WindowsDpapiCodec()
    normalized = _normalize_store(payload)
    plaintext = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")
    encrypted = active_codec.encrypt(plaintext)
    temp_path = secret_path.with_suffix(secret_path.suffix + ".tmp")
    temp_path.write_bytes(encrypted)
    temp_path.replace(secret_path)
    return secret_path


def get_provider_secret_entry(
    provider_id: str,
    path: str | Path | None = None,
    *,
    codec: SecretCodec | None = None,
) -> dict[str, Any]:
    store = load_provider_secret_store(path, codec=codec)
    providers = store.get("providers")
    if not isinstance(providers, dict):
        return {}
    entry = providers.get(str(provider_id).strip().lower())
    return dict(entry) if isinstance(entry, dict) else {}


def save_inara_secret_entry(
    *,
    commander_name: Any,
    frontier_id: Any,
    app_key: Any,
    path: str | Path | None = None,
    codec: SecretCodec | None = None,
) -> dict[str, Any]:
    store = load_provider_secret_store(path, codec=codec)
    providers = store.setdefault("providers", {})
    existing = providers.get("inara") if isinstance(providers.get("inara"), dict) else {}
    entry: dict[str, Any] = {}

    commander_text = str(commander_name or "").strip()
    if commander_text:
        entry["commander_name"] = commander_text

    frontier_text = str(frontier_id or "").strip()
    if frontier_text:
        entry["frontier_id"] = frontier_text

    app_key_text = str(app_key or "").strip()
    if app_key_text:
        entry["app_key"] = app_key_text
    elif isinstance(existing, dict) and str(existing.get("app_key") or "").strip():
        entry["app_key"] = str(existing.get("app_key") or "").strip()

    if entry:
        providers["inara"] = entry
    else:
        providers.pop("inara", None)

    save_provider_secret_store(store, path, codec=codec)
    return entry


def save_openai_secret_entry(
    *,
    api_key: Any,
    path: str | Path | None = None,
    codec: SecretCodec | None = None,
) -> dict[str, Any]:
    store = load_provider_secret_store(path, codec=codec)
    providers = store.setdefault("providers", {})
    existing = providers.get("openai") if isinstance(providers.get("openai"), dict) else {}
    entry: dict[str, Any] = {}

    api_key_text = str(api_key or "").strip()
    if api_key_text:
        entry["api_key"] = api_key_text
    elif isinstance(existing, dict) and str(existing.get("api_key") or "").strip():
        entry["api_key"] = str(existing.get("api_key") or "").strip()

    if entry:
        providers["openai"] = entry
    else:
        providers.pop("openai", None)

    save_provider_secret_store(store, path, codec=codec)
    return entry
