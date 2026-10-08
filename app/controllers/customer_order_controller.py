from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    CustomerAddress,
    Order,
    OrderExtraQuote,
    OrderOffer,
    OrderStatusHistory,
    Payment,
    Review,
    Service,
    ServiceCategory,
    User,
    Warranty,
    WorkerProfile,
    WorkerService,
)
from app.schemas.customer import (
    CancelRequest,
    CustomerOrderDetail,
    CustomerOrderItem,
    ExtraQuoteItem,
    HistoryItem,
    OrderCreate,
    OrderWorkerBrief,
    PaymentItem,
    PublicReview,
    ReviewItem,
    TrackingOut,
    WarrantyItem,
    WorkerPublicProfile,
)
from app.services.notification_service import notify
from app.utils.dates import VN_TZ, now_vn
from app.utils.pagination import paginate
from app.utils.response import paginated, success

ACTIVE_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress")
CANCELLABLE_STATUSES = ("pending", "matched", "accepted")
TRACKABLE_STATUSES = ("accepted", "on_the_way", "arrived", "in_progress")
QUOTE_OPEN_STATUSES = ("accepted", "on_the_way", "arrived", "in_progress")
STATUS_GROUPS = {
    "active": ("pending", *ACTIVE_STATUSES),
    "completed": ("completed",),
    "cancelled": ("cancelled",),
}
MAX_SCHEDULE_DAYS = 30
MAX_OPEN_ORDERS = 5


# ---------- Hàm dùng chung (các controller khác của khách cũng dùng) ----------


def get_own_order(db: Session, customer: User, order_id: int, for_update: bool = False) -> Order:
    stmt = select(Order).where(Order.id == order_id, Order.customer_id == customer.id)
    if for_update:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    return order


def add_history(db: Session, order: Order, new_status: str, user_id: int | None) -> None:
    db.add(OrderStatusHistory(order_id=order.id, status=new_status, changed_by=user_id))


def order_total(db: Session, order: Order) -> int | None:
    """Số tiền khách phải trả: giá chốt nếu thợ đã chốt, nếu không thì giá dự kiến + phát sinh đã duyệt."""
    if order.final_price is not None:
        return int(order.final_price)
    if order.estimated_price is None:
        return None
    extra = db.scalar(
        select(func.coalesce(func.sum(OrderExtraQuote.amount), 0)).where(
            OrderExtraQuote.order_id == order.id, OrderExtraQuote.status == "approved"
        )
    )
    return int(order.estimated_price) + int(extra)


def has_paid(db: Session, order_id: int) -> bool:
    return bool(
        db.scalar(select(Payment.id).where(Payment.order_id == order_id, Payment.status == "success"))
    )


def _to_naive_vn(dt: datetime) -> datetime:
    # DB lưu giờ VN không kèm múi giờ (giống utils.dates.now_vn)
    if dt.tzinfo is not None:
        dt = dt.astimezone(VN_TZ).replace(tzinfo=None)
    return dt


def _worker_briefs(db: Session, worker_ids: set[int]) -> dict[int, OrderWorkerBrief]:
    if not worker_ids:
        return {}
    rows = db.execute(
        select(User, WorkerProfile)
        .join(WorkerProfile, WorkerProfile.user_id == User.id)
        .where(User.id.in_(worker_ids))
    ).all()
    return {
        u.id: OrderWorkerBrief(
            id=u.id,
            full_name=u.full_name,
            phone=u.phone,
            avatar_url=u.avatar_url,
            trust_score=float(p.trust_score),
            review_count=p.review_count,
            completed_orders=p.completed_orders,
        )
        for u, p in rows
    }


def _item(order: Order, service_name: str, category_name: str, worker) -> CustomerOrderItem:
    return CustomerOrderItem(
        id=order.id,
        status=order.status,
        service_name=service_name,
        category_name=category_name,
        address_line=order.address_line,
        scheduled_at=order.scheduled_at,
        estimated_price=int(order.estimated_price) if order.estimated_price is not None else None,
        final_price=int(order.final_price) if order.final_price is not None else None,
        worker=worker,
        created_at=order.created_at,
        completed_at=order.completed_at,
    )


# ---------- Tạo đơn ----------


def create_order(db: Session, customer: User, data: OrderCreate):
    service = db.get(Service, data.service_id)
    if not service or not service.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dịch vụ không tồn tại hoặc đã ngừng")

    open_orders = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.customer_id == customer.id, Order.status.in_(STATUS_GROUPS["active"]))
    )
    if open_orders >= MAX_OPEN_ORDERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bạn đang có {open_orders} đơn chưa xong, tối đa {MAX_OPEN_ORDERS}"
        )

    if data.address_id is not None:
        addr = db.get(CustomerAddress, data.address_id)
        if not addr or addr.customer_id != customer.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Địa chỉ không hợp lệ")
        address_line, lat, lng = addr.address_line, addr.latitude, addr.longitude
    else:
        address_line, lat, lng = data.address_line, data.latitude, data.longitude

    scheduled_at = None
    if data.scheduled_at:
        scheduled_at = _to_naive_vn(data.scheduled_at)
        now = now_vn()
        if scheduled_at < now + timedelta(minutes=30):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lịch hẹn phải sau thời điểm hiện tại ít nhất 30 phút")
        if scheduled_at > now + timedelta(days=MAX_SCHEDULE_DAYS):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Chỉ đặt lịch trước tối đa {MAX_SCHEDULE_DAYS} ngày")

    order = Order(
        customer_id=customer.id,
        service_id=service.id,
        address_line=address_line,
        latitude=lat,
        longitude=lng,
        description=data.description,
        image_urls=data.image_urls,
        scheduled_at=scheduled_at,
        matching_mode=data.matching_mode,
        status="pending",
        estimated_price=service.base_price,
    )
    db.add(order)
    db.flush()
    add_history(db, order, "pending", customer.id)
    db.commit()

    # MATCHING_HOOK: khi có thuật toán, gọi ở đây (instant: tạo offer ngay;
    # batch: đưa vào hàng đợi theo batch_window_seconds).

    return get_order(db, customer, order.id, message="Đã tạo yêu cầu sửa chữa")


# ---------- Danh sách / chi tiết ----------


def list_orders(db: Session, customer: User, group: str | None, page: int, page_size: int):
    stmt = (
        select(Order)
        .where(Order.customer_id == customer.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if group:
        stmt = stmt.where(Order.status.in_(STATUS_GROUPS[group]))
    orders, total = paginate(db, stmt, page, page_size)

    service_ids = {o.service_id for o in orders}
    names = {
        sid: (sname, cname)
        for sid, sname, cname in db.execute(
            select(Service.id, Service.name, ServiceCategory.name)
            .join(ServiceCategory, ServiceCategory.id == Service.category_id)
            .where(Service.id.in_(service_ids))
        ).all()
    } if service_ids else {}
    workers = _worker_briefs(db, {o.worker_id for o in orders if o.worker_id})

    items = [
        _item(o, *names.get(o.service_id, ("", "")), workers.get(o.worker_id)) for o in orders
    ]
    return paginated(items, total, page, page_size)


def get_order(db: Session, customer: User, order_id: int, message: str = "OK"):
    o = get_own_order(db, customer, order_id)
    service_name, category_name = db.execute(
        select(Service.name, ServiceCategory.name)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.id == o.service_id)
    ).one()
    worker = _worker_briefs(db, {o.worker_id}).get(o.worker_id) if o.worker_id else None

    history = db.scalars(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == o.id)
        .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
    ).all()
    quotes = db.scalars(
        select(OrderExtraQuote).where(OrderExtraQuote.order_id == o.id).order_by(OrderExtraQuote.created_at)
    ).all()
    payments = db.scalars(
        select(Payment).where(Payment.order_id == o.id).order_by(Payment.created_at)
    ).all()
    review = db.scalar(select(Review).where(Review.order_id == o.id))
    warranty = db.scalar(select(Warranty).where(Warranty.order_id == o.id))
    paid = any(p.status == "success" for p in payments)

    base = _item(o, service_name, category_name, worker)
    detail = CustomerOrderDetail(
        **base.model_dump(),
        service_id=o.service_id,
        latitude=o.latitude,
        longitude=o.longitude,
        description=o.description,
        image_urls=o.image_urls or [],
        matching_mode=o.matching_mode,
        cancel_reason=o.cancel_reason,
        accepted_at=o.accepted_at,
        total_amount=order_total(db, o),
        history=[HistoryItem(status=h.status, created_at=h.created_at) for h in history],
        extra_quotes=[
            ExtraQuoteItem(
                id=q.id,
                description=q.description,
                amount=int(q.amount),
                status=q.status,
                created_at=q.created_at,
                responded_at=q.responded_at,
            )
            for q in quotes
        ],
        payments=[
            PaymentItem(
                id=p.id,
                amount=int(p.amount),
                method=p.method,
                status=p.status,
                transaction_code=p.transaction_code,
                created_at=p.created_at,
                paid_at=p.paid_at,
            )
            for p in payments
        ],
        review=ReviewItem(id=review.id, rating=review.rating, comment=review.comment, created_at=review.created_at)
        if review
        else None,
        warranty=WarrantyItem(
            id=warranty.id,
            order_id=warranty.order_id,
            terms=warranty.terms,
            start_date=warranty.start_date,
            end_date=warranty.end_date,
            status=warranty.status,
        )
        if warranty
        else None,
        can_cancel=o.status in CANCELLABLE_STATUSES,
        can_pay=o.status == "completed" and not paid,
        can_review=o.status == "completed" and o.worker_id is not None and review is None,
    )
    return success(detail, message)


# ---------- Huỷ đơn ----------


def cancel_order(db: Session, customer: User, order_id: int, data: CancelRequest):
    o = get_own_order(db, customer, order_id, for_update=True)
    if o.status not in CANCELLABLE_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không thể huỷ đơn ở trạng thái hiện tại")

    o.status = "cancelled"
    o.cancel_reason = data.reason
    add_history(db, o, "cancelled", customer.id)

    # Offer còn treo thì cho hết hạn để thợ không nhận nhầm
    db.execute(
        update(OrderOffer)
        .where(OrderOffer.order_id == o.id, OrderOffer.status == "sent")
        .values(status="expired", responded_at=now_vn())
    )
    notify(db, o.worker_id, "Khách đã huỷ đơn", f"Đơn #{o.id}: {data.reason}", "order_cancelled", o.id)
    db.commit()
    return success({"id": o.id, "status": o.status}, "Đã huỷ đơn")


# ---------- Theo dõi thợ ----------


def get_tracking(db: Session, customer: User, order_id: int):
    o = get_own_order(db, customer, order_id)
    lat = lng = updated = None
    if o.worker_id and o.status in TRACKABLE_STATUSES:
        p = db.get(WorkerProfile, o.worker_id)
        if p:
            lat, lng, updated = p.current_latitude, p.current_longitude, p.location_updated_at
    return success(
        TrackingOut(
            order_id=o.id,
            status=o.status,
            destination_latitude=o.latitude,
            destination_longitude=o.longitude,
            worker_latitude=lat,
            worker_longitude=lng,
            location_updated_at=updated,
        )
    )


# ---------- Báo giá phát sinh ----------


def respond_extra_quote(db: Session, customer: User, order_id: int, quote_id: int, approve: bool):
    o = get_own_order(db, customer, order_id, for_update=True)
    if o.status not in QUOTE_OPEN_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn không còn nhận báo giá phát sinh")
    q = db.scalar(
        select(OrderExtraQuote).where(OrderExtraQuote.id == quote_id, OrderExtraQuote.order_id == o.id)
    )
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy báo giá")
    if q.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Báo giá này đã được xử lý")

    q.status = "approved" if approve else "rejected"
    q.responded_at = now_vn()
    notify(
        db,
        q.worker_id,
        "Khách đã duyệt báo giá" if approve else "Khách từ chối báo giá",
        f"Đơn #{o.id}: {q.description} ({int(q.amount):,}đ)",
        "extra_quote",
        o.id,
    )
    db.commit()
    return success(
        {"id": q.id, "status": q.status, "total_amount": order_total(db, o)},
        "Đã duyệt báo giá" if approve else "Đã từ chối báo giá",
    )


# ---------- Hồ sơ thợ ----------


def get_worker_profile(db: Session, worker_id: int):
    row = db.execute(
        select(User, WorkerProfile)
        .join(WorkerProfile, WorkerProfile.user_id == User.id)
        .where(User.id == worker_id, WorkerProfile.verification_status == "approved")
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thợ")
    u, p = row

    services = db.scalars(
        select(Service.name)
        .join(WorkerService, WorkerService.service_id == Service.id)
        .where(WorkerService.worker_id == u.id, Service.is_active.is_(True))
        .order_by(Service.name)
    ).all()
    reviews = db.execute(
        select(Review, User.full_name)
        .join(User, User.id == Review.customer_id)
        .where(Review.worker_id == u.id, Review.is_hidden.is_(False))
        .order_by(Review.created_at.desc())
        .limit(10)
    ).all()

    return success(
        WorkerPublicProfile(
            id=u.id,
            full_name=u.full_name,
            avatar_url=u.avatar_url,
            bio=p.bio,
            experience_years=p.experience_years,
            trust_score=float(p.trust_score),
            review_count=p.review_count,
            completed_orders=p.completed_orders,
            services=list(services),
            recent_reviews=[
                PublicReview(rating=r.rating, comment=r.comment, customer_name=name, created_at=r.created_at)
                for r, name in reviews
            ],
        )
    )
