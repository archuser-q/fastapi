import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.controllers.customer_order_controller import get_own_order, order_total
from app.models import Order, Payment, Service, User
from app.schemas.customer import MyPaymentItem, PaymentCreate, PaymentOut
from app.services.notification_service import notify
from app.utils.dates import now_vn
from app.utils.response import paginated, success


def _out(p: Payment, pay_url: str | None = None) -> PaymentOut:
    return PaymentOut(
        id=p.id,
        order_id=p.order_id,
        amount=int(p.amount),
        method=p.method,
        status=p.status,
        transaction_code=p.transaction_code,
        created_at=p.created_at,
        paid_at=p.paid_at,
        pay_url=pay_url,
    )


def create_payment(db: Session, customer: User, order_id: int, data: PaymentCreate):
    o = get_own_order(db, customer, order_id, for_update=True)
    if o.status != "completed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chỉ thanh toán khi đơn đã hoàn thành")
    if db.scalar(select(Payment.id).where(Payment.order_id == o.id, Payment.status == "success")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn đã được thanh toán")

    amount = order_total(db, o)
    if not amount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn chưa có số tiền thanh toán")

    # Mỗi đơn chỉ giữ 1 payment đang chờ: huỷ cái cũ nếu khách đổi phương thức
    db.execute(
        update(Payment)
        .where(Payment.order_id == o.id, Payment.status == "pending")
        .values(status="failed")
    )
    p = Payment(order_id=o.id, amount=amount, method=data.method, status="pending")
    db.add(p)
    if data.method == "cash":
        notify(db, o.worker_id, "Khách chọn trả tiền mặt", f"Đơn #{o.id}: thu {amount:,}đ", "payment", o.id)
    db.commit()
    db.refresh(p)

    # TODO: momo/vnpay -> gọi API sandbox lấy pay_url
    return success(_out(p), "Đã tạo thanh toán")


def sandbox_confirm(db: Session, customer: User, payment_id: int):
    if not settings.debug:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

    p = db.scalar(
        select(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.id == payment_id, Order.customer_id == customer.id)
        .with_for_update()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thanh toán")
    if p.method == "cash":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tiền mặt do thợ xác nhận")
    if p.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Thanh toán không còn ở trạng thái chờ")

    p.status = "success"
    p.paid_at = now_vn()
    p.transaction_code = f"SANDBOX-{uuid.uuid4().hex[:12].upper()}"
    o = db.get(Order, p.order_id)
    notify(db, o.worker_id, "Khách đã thanh toán", f"Đơn #{o.id}: {int(p.amount):,}đ", "payment", o.id)
    db.commit()
    db.refresh(p)
    return success(_out(p), "Thanh toán thành công")


def list_payments(db: Session, customer: User, order_id: int):
    o = get_own_order(db, customer, order_id)
    rows = db.scalars(select(Payment).where(Payment.order_id == o.id).order_by(Payment.created_at)).all()
    return success([_out(p) for p in rows])


def list_my_payments(db: Session, customer: User, page: int, page_size: int):
    """Lịch sử giao dịch: mọi payment của khách, mới nhất trước."""
    stmt = (
        select(Payment, Service.name)
        .join(Order, Order.id == Payment.order_id)
        .join(Service, Service.id == Order.service_id)
        .where(Order.customer_id == customer.id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        MyPaymentItem(
            id=p.id,
            order_id=p.order_id,
            service_name=sname,
            amount=int(p.amount),
            method=p.method,
            status=p.status,
            transaction_code=p.transaction_code,
            created_at=p.created_at,
            paid_at=p.paid_at,
        )
        for p, sname in rows
    ]
    return paginated(items, total, page, page_size)
