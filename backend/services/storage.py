"""Object storage: writes bytes to LOCAL_UPLOAD_DIR on disk.

Exposes ``put_object(path, data, ct)`` returning ``{"path": ..., "size": int}``
and ``get_object(path)`` returning ``(bytes, content_type)``.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


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


def init() -> None:
    logger.info(f"Local storage initialized at {_local_root()}")


def put_object(path: str, data: bytes, content_type: str) -> dict:
    target = _safe_local_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": path, "size": len(data)}


def get_object(path: str) -> Tuple[bytes, str]:
    target = _safe_local_path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    ct, _ = mimetypes.guess_type(target.name)
    return target.read_bytes(), ct or "application/octet-stream"
