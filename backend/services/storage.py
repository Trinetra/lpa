"""Pluggable object storage.

Two backends, selected by ``STORAGE_BACKEND`` env var:

- ``emergent`` (default) — the Emergent-managed object storage proxy at
  ``integrations.emergentagent.com/objstore``. Required inside Emergent preview.
- ``local`` — writes bytes to ``LOCAL_UPLOAD_DIR`` on disk. Used when the app
  is self-hosted (e.g. on a VPS).

Both backends expose the same tiny interface: ``put_object(path, data, ct)``
returns ``{"path": ..., "size": int}`` and ``get_object(path)`` returns
``(bytes, content_type)``. ``init()`` may be a no-op for local storage.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_EMERGENT_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"


def _backend() -> str:
    return os.environ.get("STORAGE_BACKEND", "emergent").lower()


# ---------------- Emergent-hosted backend ----------------
_emergent_key: Optional[str] = None


def _emergent_init() -> str:
    global _emergent_key
    if _emergent_key:
        return _emergent_key
    resp = requests.post(
        f"{_EMERGENT_URL}/init",
        json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")},
        timeout=30,
    )
    resp.raise_for_status()
    _emergent_key = resp.json()["storage_key"]
    return _emergent_key


def _emergent_put(path: str, data: bytes, content_type: str) -> dict:
    key = _emergent_init()
    resp = requests.put(
        f"{_EMERGENT_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _emergent_get(path: str) -> Tuple[bytes, str]:
    key = _emergent_init()
    resp = requests.get(
        f"{_EMERGENT_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# ---------------- Local filesystem backend ----------------
def _local_root() -> Path:
    root = Path(os.environ.get("LOCAL_UPLOAD_DIR", "/data/uploads"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_local_path(path: str) -> Path:
    root = _local_root().resolve()
    target = (root / path).resolve()
    # Reject any path that escapes the upload root.
    if root not in target.parents and target != root:
        raise ValueError("path escapes upload root")
    return target


def _local_put(path: str, data: bytes, content_type: str) -> dict:
    target = _safe_local_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": path, "size": len(data)}


def _local_get(path: str) -> Tuple[bytes, str]:
    target = _safe_local_path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    ct, _ = mimetypes.guess_type(target.name)
    return target.read_bytes(), ct or "application/octet-stream"


# ---------------- Public API ----------------
def init() -> None:
    if _backend() == "emergent":
        _emergent_init()
    else:
        _local_root()
        logger.info(f"Local storage initialized at {_local_root()}")


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if _backend() == "emergent":
        return _emergent_put(path, data, content_type)
    return _local_put(path, data, content_type)


def get_object(path: str) -> Tuple[bytes, str]:
    if _backend() == "emergent":
        return _emergent_get(path)
    return _local_get(path)
