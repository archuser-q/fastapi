"""App khách hàng: đơn hàng, thanh toán, đánh giá, khiếu nại, bảo hành."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import customer_order_controller as orders
from app.controllers import customer_payment_controller as payments
from app.controllers import customer_support_controller as support
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.customer import (
    CancelRequest,
    ComplaintCreate,
    OrderCreate,
    PaymentCreate,
    ReviewCreate,
    WarrantyClaim,
)

customer_only = require_roles("customer")

router = APIRouter(prefix="/customer", tags=["Customer App - Orders"])


# ---------- Đơn hàng ----------


@router.post("/orders", status_code=201)
def create_order(data: OrderCreate, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return orders.create_order(db, user, data)


@router.get("/orders")
def list_orders(
    group: Literal["active", "completed", "cancelled"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    return orders.list_orders(db, user, group, page, page_size)


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return orders.get_order(db, user, order_id)


@router.patch("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int, data: CancelRequest, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return orders.cancel_order(db, user, order_id, data)


@router.get("/orders/{order_id}/tracking")
def get_tracking(order_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return orders.get_tracking(db, user, order_id)


@router.post("/orders/{order_id}/extra-quotes/{quote_id}/approve")
def approve_quote(order_id: int, quote_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return orders.respond_extra_quote(db, user, order_id, quote_id, approve=True)


@router.post("/orders/{order_id}/extra-quotes/{quote_id}/reject")
def reject_quote(order_id: int, quote_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return orders.respond_extra_quote(db, user, order_id, quote_id, approve=False)


@router.get("/workers/{worker_id}")
def get_worker(worker_id: int, db: Session = Depends(get_db), _: User = Depends(customer_only)):
    return orders.get_worker_profile(db, worker_id)


# ---------- Thanh toán ----------


@router.get("/orders/{order_id}/payments")
def list_payments(order_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return payments.list_payments(db, user, order_id)


@router.post("/orders/{order_id}/payments", status_code=201)
def create_payment(
    order_id: int, data: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return payments.create_payment(db, user, order_id, data)


@router.get("/payments")
def list_my_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    return payments.list_my_payments(db, user, page, page_size)


@router.post("/payments/{payment_id}/sandbox-confirm", include_in_schema=True)
def sandbox_confirm(payment_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    """Giả lập cổng MoMo/VNPay báo thành công. Chỉ chạy khi DEBUG=true."""
    return payments.sandbox_confirm(db, user, payment_id)


# ---------- Đánh giá, khiếu nại, bảo hành ----------


@router.post("/orders/{order_id}/review", status_code=201)
def create_review(
    order_id: int, data: ReviewCreate, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return support.create_review(db, user, order_id, data)


@router.get("/reviews")
def list_my_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    return support.list_my_reviews(db, user, page, page_size)


@router.post("/orders/{order_id}/complaints", status_code=201)
def create_complaint(
    order_id: int, data: ComplaintCreate, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return support.create_complaint(db, user, order_id, data)


@router.get("/complaints")
def list_complaints(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(customer_only),
):
    return support.list_complaints(db, user, page, page_size)


@router.get("/warranties")
def list_warranties(db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return support.list_warranties(db, user)


@router.post("/warranties/{warranty_id}/claim", status_code=201)
def claim_warranty(
    warranty_id: int, data: WarrantyClaim, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return support.claim_warranty(db, user, warranty_id, data)
