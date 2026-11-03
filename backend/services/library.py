"""Library files in Cloudflare R2 (bucket R2_BUCKET).

Files go straight from the browser to R2 through presigned multipart uploads;
the backend only signs URLs, finishes uploads, makes image thumbnails and
deletes. Everything in the bucket is private — reads are presigned GETs that
expire after an hour.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from urllib.parse import quote

import boto3
import pillow_heif
from botocore.config import Config
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()  # iPhone/Mac HEIC photos

MIB = 1024 * 1024
MIN_PART = 16 * MIB
MAX_PARTS = 10_000
URL_TTL = 3600
THUMB_MAX_SOURCE = 80 * MIB  # bigger images just get no thumbnail
THUMB_SIZE = 800


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _bucket() -> str:
    return os.environ["R2_BUCKET"]


def part_size(size: int) -> int:
    """Smallest whole-MiB part size (at least 16 MiB) that fits in 10,000 parts."""
    needed = -(-size // MAX_PARTS)
    return max(MIN_PART, -(-needed // MIB) * MIB)


def start_upload(key: str, content_type: str) -> str:
    r = _client().create_multipart_upload(Bucket=_bucket(), Key=key, ContentType=content_type)
    return r["UploadId"]


def part_urls(key: str, upload_id: str, numbers: list[int]) -> dict[int, str]:
    c = _client()
    return {
        n: c.generate_presigned_url(
            "upload_part",
            Params={"Bucket": _bucket(), "Key": key, "UploadId": upload_id, "PartNumber": n},
            ExpiresIn=URL_TTL,
        )
        for n in numbers
    }


def complete_upload(key: str, upload_id: str, parts: list[dict]) -> None:
    _client().complete_multipart_upload(
        Bucket=_bucket(), Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": p["part_number"], "ETag": p["etag"]} for p in parts]},
    )


def abort_upload(key: str, upload_id: str) -> None:
    try:
        _client().abort_multipart_upload(Bucket=_bucket(), Key=key, UploadId=upload_id)
    except Exception:
        pass  # already completed/aborted, or expired by R2


def get_url(key: str, download_name: str | None = None) -> str:
    params = {"Bucket": _bucket(), "Key": key}
    if download_name:
        # RFC 5987 so IAST titles (Nṛtyārpaṇa…) survive, plus an ASCII fallback.
        ascii_name = download_name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
        params["ResponseContentDisposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(download_name)}"
    return _client().generate_presigned_url("get_object", Params=params, ExpiresIn=URL_TTL)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def delete(keys: list[str]) -> None:
    keys = [k for k in keys if k]
    if keys:
        _client().delete_objects(Bucket=_bucket(), Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True})


def make_thumbnail(key: str, size: int) -> bytes | None:
    """JPEG preview of an uploaded image (HEIC included), or None if it can't be read."""
    if size > THUMB_MAX_SOURCE:
        return None
    try:
        data = _client().get_object(Bucket=_bucket(), Key=key)["Body"].read()
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80, optimize=True)
        return out.getvalue()
    except Exception:
        return None
