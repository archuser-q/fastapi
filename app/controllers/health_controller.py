from sqlalchemy import text
from sqlalchemy.orm import Session

from app.utils.response import success


def check_health():
    return success({"status": "running"})


def check_db(db: Session):
    db.execute(text("SELECT 1"))
    return success({"database": "connected"})