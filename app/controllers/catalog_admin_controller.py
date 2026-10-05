import math
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Order, Service, ServiceCategory, WorkerService
from app.schemas.catalog_admin import (
    MAX_PRICE,
    BulkPriceChange,
    BulkPriceResult,
    BulkPriceUpdate,
    CategoryCreate,
    CategoryItem,
    CategoryUpdate,
    ServiceCreate,
    ServiceItem,
    ServiceUpdate,
)
from app.utils.dates import now_vn
from app.utils.response import paginated, success


# ---------- Danh mục ----------


def _get_category(db: Session, category_id: int) -> ServiceCategory:
    category = db.get(ServiceCategory, category_id)
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy danh mục")
    return category


def _ensure_unique_category(db: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(ServiceCategory.id).where(func.lower(ServiceCategory.name) == name.lower())
    if exclude_id:
        stmt = stmt.where(ServiceCategory.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Danh mục \"{name}\" đã tồn tại")


def _category_items(db: Session, category_id: int | None = None) -> list[CategoryItem]:
    counts = (
        select(
            Service.category_id,
            func.count().label("total"),
            func.count().filter(Service.is_active.is_(True)).label("active"),
        )
        .group_by(Service.category_id)
        .subquery()
    )
    stmt = (
        select(ServiceCategory, counts.c.total, counts.c.active)
        .outerjoin(counts, counts.c.category_id == ServiceCategory.id)
        .order_by(ServiceCategory.name)
    )
    if category_id:
        stmt = stmt.where(ServiceCategory.id == category_id)
    return [
        CategoryItem(
            id=c.id,
            parent_id=c.parent_id,
            name=c.name,
            description=c.description,
            icon_url=c.icon_url,
            is_active=c.is_active,
            services_total=total or 0,
            services_active=active or 0,
        )
        for c, total, active in db.execute(stmt).all()
    ]


def list_categories(db: Session):
    return success(_category_items(db))


def create_category(db: Session, data: CategoryCreate):
    _ensure_unique_category(db, data.name)
    if data.parent_id:
        _get_category(db, data.parent_id)
    category = ServiceCategory(**data.model_dump())
    db.add(category)
    db.commit()
    return success(_category_items(db, category.id)[0], "Đã thêm danh mục")


def update_category(db: Session, category_id: int, data: CategoryUpdate):
    category = _get_category(db, category_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        _ensure_unique_category(db, changes["name"], exclude_id=category_id)
    if "name" in changes and not changes["name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên danh mục không được để trống")
    for key, value in changes.items():
        setattr(category, key, value)
    db.commit()
    return success(_category_items(db, category_id)[0], "Đã cập nhật danh mục")


def delete_category(db: Session, category_id: int):
    category = _get_category(db, category_id)
    if db.scalar(select(func.count(Service.id)).where(Service.category_id == category_id)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Danh mục còn dịch vụ, hãy chuyển hoặc xóa dịch vụ trước, hoặc tạm ẩn danh mục",
        )
    if db.scalar(
        select(func.count(ServiceCategory.id)).where(ServiceCategory.parent_id == category_id)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh mục còn danh mục con")
    db.delete(category)
    db.commit()
    return success(message="Đã xóa danh mục")


# ---------- Dịch vụ ----------


def _service_query():
    since = now_vn() - timedelta(days=30)
    workers = (
        select(WorkerService.service_id, func.count().label("n"))
        .group_by(WorkerService.service_id)
        .subquery()
    )
    orders = (
        select(
            Order.service_id,
            func.count().label("n"),
            func.avg(Order.final_price).filter(Order.status == "completed").label("avg_price"),
        )
        .where(Order.created_at >= since)
        .group_by(Order.service_id)
        .subquery()
    )
    return (
        select(Service, ServiceCategory.name, workers.c.n, orders.c.n, orders.c.avg_price)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .outerjoin(workers, workers.c.service_id == Service.id)
        .outerjoin(orders, orders.c.service_id == Service.id)
    )


def _to_item(row) -> ServiceItem:
    s, category_name, workers, orders_30d, avg_price = row
    return ServiceItem(
        id=s.id,
        category_id=s.category_id,
        category_name=category_name,
        name=s.name,
        description=s.description,
        base_price=int(s.base_price),
        unit=s.unit,
        is_active=s.is_active,
        workers=workers or 0,
        orders_30d=orders_30d or 0,
        avg_final_price_30d=round(float(avg_price)) if avg_price is not None else None,
    )


def _service_item(db: Session, service_id: int) -> ServiceItem:
    return _to_item(db.execute(_service_query().where(Service.id == service_id)).one())


def _get_service(db: Session, service_id: int) -> Service:
    service = db.get(Service, service_id)
    if not service:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy dịch vụ")
    return service


def _ensure_unique_service(db: Session, category_id: int, name: str, exclude_id: int | None = None):
    stmt = select(Service.id).where(
        Service.category_id == category_id, func.lower(Service.name) == name.lower()
    )
    if exclude_id:
        stmt = stmt.where(Service.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Dịch vụ \"{name}\" đã có trong danh mục này"
        )


def list_services(db: Session, category_id, keyword, active, page, page_size):
    stmt = _service_query()
    if category_id:
        stmt = stmt.where(Service.category_id == category_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Service.name.ilike(like), Service.description.ilike(like)))
    if active is not None:
        stmt = stmt.where(Service.is_active.is_(active))

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(
        stmt.order_by(ServiceCategory.name, Service.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return paginated([_to_item(r) for r in rows], total, page, page_size)


def create_service(db: Session, data: ServiceCreate):
    _get_category(db, data.category_id)
    _ensure_unique_service(db, data.category_id, data.name)
    service = Service(**data.model_dump())
    db.add(service)
    db.commit()
    return success(_service_item(db, service.id), "Đã thêm dịch vụ")


def update_service(db: Session, service_id: int, data: ServiceUpdate):
    service = _get_service(db, service_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and not changes["name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên dịch vụ không được để trống")
    if "base_price" in changes and changes["base_price"] is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Giá gốc không được để trống")

    category_id = changes.get("category_id") or service.category_id
    if "category_id" in changes:
        _get_category(db, category_id)
    if "name" in changes or "category_id" in changes:
        _ensure_unique_service(db, category_id, changes.get("name") or service.name, service.id)

    for key, value in changes.items():
        setattr(service, key, value)
    db.commit()
    return success(_service_item(db, service_id), "Đã cập nhật dịch vụ")


def delete_service(db: Session, service_id: int):
    service = _get_service(db, service_id)
    if db.scalar(select(func.count(Order.id)).where(Order.service_id == service_id)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Dịch vụ đã có đơn hàng nên không xóa được, hãy tạm ẩn dịch vụ thay vì xóa",
        )
    db.execute(WorkerService.__table__.delete().where(WorkerService.service_id == service_id))
    db.delete(service)
    db.commit()
    return success(message="Đã xóa dịch vụ")


def _round(value: float, step: int) -> int:
    # Làm tròn .5 lên trên, giống Math.round ở frontend để bảng xem trước khớp với giá lưu thật
    return int(math.floor(value / step + 0.5) * step)


def bulk_update_price(db: Session, data: BulkPriceUpdate):
    services = db.scalars(select(Service).where(Service.id.in_(data.service_ids))).all()
    if len(services) != len(set(data.service_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Có dịch vụ không tồn tại trong danh sách")

    changes = []
    for s in services:
        old = int(s.base_price)
        raw = old * (1 + data.value / 100) if data.mode == "percent" else old + data.value
        new = _round(raw, data.round_to)
        if new <= 0 or new > MAX_PRICE:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Giá mới của \"{s.name}\" không hợp lệ ({new:,}đ)".replace(",", "."),
            )
        changes.append(BulkPriceChange(id=s.id, name=s.name, old_price=old, new_price=new))
        s.base_price = new

    db.commit()
    return success(
        BulkPriceResult(updated=len(changes), changes=changes, applied_at=now_vn()),
        f"Đã cập nhật giá {len(changes)} dịch vụ",
    )
