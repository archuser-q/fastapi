from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import catalog_admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.schemas.catalog_admin import (
    BulkPriceUpdate,
    CategoryCreate,
    CategoryUpdate,
    ServiceCreate,
    ServiceUpdate,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin - Services & Pricing"],
    dependencies=[Depends(require_roles("admin"))],
)


# ---------- Danh mục ----------


@router.get("/service-categories")
def list_categories(db: Session = Depends(get_db)):
    return catalog_admin_controller.list_categories(db)


@router.post("/service-categories")
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    return catalog_admin_controller.create_category(db, data)


@router.patch("/service-categories/{category_id}")
def update_category(category_id: int, data: CategoryUpdate, db: Session = Depends(get_db)):
    return catalog_admin_controller.update_category(db, category_id, data)


@router.delete("/service-categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    return catalog_admin_controller.delete_category(db, category_id)


# ---------- Dịch vụ ----------


@router.get("/services")
def list_services(
    category_id: int | None = None,
    keyword: str | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return catalog_admin_controller.list_services(db, category_id, keyword, active, page, page_size)


@router.post("/services")
def create_service(data: ServiceCreate, db: Session = Depends(get_db)):
    return catalog_admin_controller.create_service(db, data)


# Đặt trước /services/{service_id} để "bulk-price" không bị hiểu nhầm là id
@router.patch("/services/bulk-price")
def bulk_update_price(data: BulkPriceUpdate, db: Session = Depends(get_db)):
    return catalog_admin_controller.bulk_update_price(db, data)


@router.patch("/services/{service_id}")
def update_service(service_id: int, data: ServiceUpdate, db: Session = Depends(get_db)):
    return catalog_admin_controller.update_service(db, service_id, data)


@router.delete("/services/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db)):
    return catalog_admin_controller.delete_service(db, service_id)
