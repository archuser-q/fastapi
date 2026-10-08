"""Danh mục dịch vụ cho app (chỉ hiện mục đang bật)."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Service, ServiceCategory
from app.schemas.customer import CatalogCategory, CatalogService
from app.utils.response import success


def _service_out(s: Service) -> CatalogService:
    return CatalogService(
        id=s.id,
        category_id=s.category_id,
        name=s.name,
        description=s.description,
        base_price=int(s.base_price),
        unit=s.unit,
    )


def list_categories(db: Session):
    count = (
        select(Service.category_id, func.count().label("n"))
        .where(Service.is_active.is_(True))
        .group_by(Service.category_id)
        .subquery()
    )
    rows = db.execute(
        select(ServiceCategory, func.coalesce(count.c.n, 0))
        .outerjoin(count, count.c.category_id == ServiceCategory.id)
        .where(ServiceCategory.is_active.is_(True))
        .order_by(ServiceCategory.name)
    ).all()
    return success(
        [
            CatalogCategory(
                id=c.id,
                parent_id=c.parent_id,
                name=c.name,
                description=c.description,
                icon_url=c.icon_url,
                services_count=n,
            )
            for c, n in rows
        ]
    )


def list_services(db: Session, category_id: int | None, keyword: str | None):
    stmt = (
        select(Service)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.is_active.is_(True), ServiceCategory.is_active.is_(True))
    )
    if category_id:
        stmt = stmt.where(Service.category_id == category_id)
    if keyword and keyword.strip():
        stmt = stmt.where(Service.name.ilike(f"%{keyword.strip()}%"))
    rows = db.scalars(stmt.order_by(Service.name)).all()
    return success([_service_out(s) for s in rows])


def get_service(db: Session, service_id: int):
    s = db.get(Service, service_id)
    if not s or not s.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy dịch vụ")
    return success(_service_out(s))
