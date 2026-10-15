"""Ảnh minh hoạ cho dữ liệu demo (giấy tờ thợ, ảnh trước/sau khi sửa).

Dùng PNG có sẵn trong db/seed_assets — app điện thoại (React Native) không hiển thị được SVG.
Ảnh được chép vào thư mục media (volume) mỗi lần seed, nên xoá volume media vẫn tự có lại.
"""

import shutil
from pathlib import Path

from sqlalchemy import text

from app.config import settings

ASSETS = Path(__file__).with_name("seed_assets")
NAMES = ("id_card_front", "id_card_back", "portrait", "certificate", "job-before", "job-after")


def seed_media_urls() -> dict[str, str]:
    """Chép ảnh mẫu vào media/seed (nếu chưa có hoặc khác) và trả về {tên: URL}."""
    folder = Path(settings.media_dir) / "seed"
    folder.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        src, dst = ASSETS / f"{name}.png", folder / f"{name}.png"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dst)
    base = (settings.public_base_url or "http://localhost:8000").rstrip("/") + settings.media_url_prefix + "/seed"
    return {name: f"{base}/{name}.png" for name in NAMES}


def upgrade_svg_urls(db) -> int:
    """CSDL seed bằng bản cũ (ảnh .svg) -> đổi sang .png. Chạy nhiều lần không sao."""
    pattern = r"(/seed/(?:" + "|".join(NAMES) + r"))\.svg$"
    n = 0
    for table, col in (("order_photos", "url"), ("worker_documents", "file_url")):
        n += db.execute(
            text(f"UPDATE {table} SET {col} = regexp_replace({col}, :p, '\\1.png') WHERE {col} ~ :p"),
            {"p": pattern},
        ).rowcount
    return n
