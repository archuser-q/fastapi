from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import order_admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.order_admin import CancelOrderRequest

admin_only = require_roles("admin")

router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin - Orders"],
    dependencies=[Depends(admin_only)],
)

OrderStatusFilter = Literal[
    "active",
    "pending",
    "matched",
    "accepted",
    "on_the_way",
    "arrived",
    "in_progress",
    "completed",
    "cancelled",
]


@router.get("")
def list_orders(
    order_status: OrderStatusFilter | None = Query(None, alias="status"),
    keyword: str | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return order_admin_controller.list_orders(
        db, order_status, keyword, category_id, date_from, date_to, page, page_size
    )


@router.get("/status-counts")
def get_status_counts(
    keyword: str | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return order_admin_controller.get_status_counts(db, keyword, category_id, date_from, date_to)


@router.get("/filter-options")
def get_filter_options(db: Session = Depends(get_db)):
    return order_admin_controller.get_filter_options(db)


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    return order_admin_controller.get_order(db, order_id)


@router.patch("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    data: CancelOrderRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return order_admin_controller.cancel_order(db, admin, order_id, data)
