from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# Đặt múi giờ cho mọi kết nối: cột TIMESTAMP (không múi giờ) mặc định NOW() sẽ là giờ Việt Nam,
# khớp với now_vn() mà code đang dùng (trước đây DB trong Docker chạy UTC nên lệch 7 tiếng).
_connect_args = {}
if settings.database_url.startswith("postgresql") and settings.db_timezone:
    _connect_args["options"] = f"-c timezone={settings.db_timezone}"

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
