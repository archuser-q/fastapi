"""Tải ảnh lên (dùng chung cho cả 3 app): giấy tờ thợ, ảnh trước/sau, ảnh chat, ảnh đại diện, ảnh sự cố.

Ảnh lưu ở thư mục MEDIA_DIR (Docker: volume `media`) và được phục vụ tại /media/...
Tên file là chuỗi ngẫu nhiên (UUID) nên không đoán được đường dẫn.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.config import settings
from app.middleware.auth import get_current_user
from app.models import User
from app.utils.dates import now_vn
from app.utils.response import success

router = APIRouter(tags=["Uploads"])

CHUNK = 1024 * 256


def _detect(head: bytes) -> str | None:
    """Nhận dạng định dạng ảnh theo vài byte đầu (không tin Content-Type do client gửi)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heif"):
        return "heic"
    return None


def media_root() -> Path:
    root = Path(settings.media_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post("/uploads", status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...), user: User = Depends(get_current_user)):
    max_bytes = settings.upload_max_mb * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(CHUNK):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Ảnh tối đa {settings.upload_max_mb} MB")
    ext = _detect(bytes(data[:16]))
    if not ext:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chỉ nhận ảnh JPG, PNG, WEBP hoặc HEIC")

    now = now_vn()
    rel = Path(f"{now:%Y}/{now:%m}") / f"{uuid.uuid4().hex}.{ext}"
    dest = media_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    url = f"{base}{settings.media_url_prefix}/{rel.as_posix()}"
    return success({"url": url, "path": rel.as_posix(), "size": len(data), "content_type": f"image/{ext}"}, "Đã tải ảnh lên")
