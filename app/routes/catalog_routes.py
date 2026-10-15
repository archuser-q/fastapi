"""Danh mục dịch vụ công khai cho app (không cần đăng nhập)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.controllers import catalog_controller
from app.database import get_db

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    return catalog_controller.list_categories(db)


@router.get("/services")
def list_services(category_id: int | None = None, keyword: str | None = None, db: Session = Depends(get_db)):
    return catalog_controller.list_services(db, category_id, keyword)


@router.get("/services/{service_id}")
def get_service(service_id: int, db: Session = Depends(get_db)):
    return catalog_controller.get_service(db, service_id)
