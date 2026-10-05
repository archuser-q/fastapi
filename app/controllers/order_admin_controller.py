from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Complaint,
    Order,
    OrderExtraQuote,
    OrderOffer,
    OrderStatusHistory,
    Payment,
    Review,
    Service,
    ServiceCategory,
    User,
    WorkerEarning,
    WorkerProfile,
)
from app.schemas.order_admin import (
    CancelOrderRequest,
    CategoryOption,
    OrderComplaintItem,
    OrderDetail,
    OrderEarning,
    OrderExtraQuoteItem,
    OrderFilterOptions,
    OrderHistoryItem,
    OrderListItem,
    OrderOfferItem,
    OrderPaymentItem,
    OrderPerson,
    OrderReview,
    OrderService,
    OrderStatusCounts,
    OrderWorker,
    StatusCount,
)
from app.utils.dates import now_vn
from app.utils.response import paginated, success

ORDER_STATUSES = (
    "pending",
    "matched",
    "accepted",
    "on_the_way",
    "arrived",
    "in_progress",
    "completed",
    "cancelled",
)
ACTIVE_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress")
CANCELLABLE_STATUSES = ("pending", *ACTIVE_STATUSES)
OPEN_COMPLAINT = ("open", "processing")


def _int(value) -> int | None:
    return int(value) if value is not None else None


def _person(user: User | None) -> OrderPerson | None:
    if user is None:
        return None
    return OrderPerson(id=user.id, full_name=user.full_name, phone=user.phone, avatar_url=user.avatar_url)


# ---------- Bộ lọc dùng chung cho danh sách và số đếm ----------


def _filters(customer, worker, keyword, category_id, date_from: date | None, date_to: date | None):
    conditions = []
    if keyword:
        text = keyword.strip()
        if text.startswith("#") and text[1:].isdigit():
            # "#123" là tìm đúng mã đơn
            conditions.append(Order.id == int(text[1:]))
        else:
            like = f"%{text}%"
            matches = [
                customer.full_name.ilike(like),
                customer.phone.ilike(like),
                worker.full_name.ilike(like),
                worker.phone.ilike(like),
                Order.address_line.ilike(like),
            ]
            if text.isdigit():
                matches.append(Order.id == int(text))
            conditions.append(or_(*matches))
    if category_id:
        conditions.append(Service.category_id == category_id)
    if date_from:
        conditions.append(Order.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(Order.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    return conditions


def _base_query(stmt, customer, worker):
    return (
        stmt.select_from(Order)
        .join(customer, customer.id == Order.customer_id)
        .outerjoin(worker, worker.id == Order.worker_id)
        .join(Service, Service.id == Order.service_id)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
    )


def list_orders(db: Session, order_status, keyword, category_id, date_from, date_to, page, page_size):
    customer = aliased(User)
    worker = aliased(User)
    open_complaint = exists().where(
        Complaint.order_id == Order.id, Complaint.status.in_(OPEN_COMPLAINT)
    )

    stmt = _base_query(
        select(Order, customer, worker, Service.name, ServiceCategory.name, open_complaint),
        customer,
        worker,
    ).where(*_filters(customer, worker, keyword, category_id, date_from, date_to))

    if order_status == "active":
        stmt = stmt.where(Order.status.in_(ACTIVE_STATUSES))
    elif order_status:
        stmt = stmt.where(Order.status == order_status)

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(
        stmt.order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        OrderListItem(
            id=o.id,
            status=o.status,
            customer=_person(c),
            worker=_person(w),
            service_name=service_name,
            category_name=category_name,
            address_line=o.address_line,
            amount=_int(o.final_price if o.final_price is not None else o.estimated_price),
            matching_mode=o.matching_mode,
            scheduled_at=o.scheduled_at,
            created_at=o.created_at,
            completed_at=o.completed_at,
            has_open_complaint=has_complaint,
        )
        for o, c, w, service_name, category_name, has_complaint in rows
    ]
    return paginated(items, total, page, page_size)


def get_status_counts(db: Session, keyword, category_id, date_from, date_to):
    customer = aliased(User)
    worker = aliased(User)
    rows = db.execute(
        _base_query(select(Order.status, func.count()), customer, worker)
        .where(*_filters(customer, worker, keyword, category_id, date_from, date_to))
        .group_by(Order.status)
    ).all()
    counts = dict(rows)
    return success(
        OrderStatusCounts(
            total=sum(counts.values()),
            items=[StatusCount(status=s, count=counts.get(s, 0)) for s in ORDER_STATUSES],
        )
    )


def get_filter_options(db: Session):
    categories = db.execute(
        select(ServiceCategory.id, ServiceCategory.name).order_by(ServiceCategory.name)
    ).all()
    return success(
        OrderFilterOptions(categories=[CategoryOption(id=c.id, name=c.name) for c in categories])
    )


# ---------- Chi tiết đơn ----------


def _get_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    return order


def _history(db: Session, order_id: int) -> list[OrderHistoryItem]:
    rows = db.execute(
        select(OrderStatusHistory, User.full_name, User.role)
        .outerjoin(User, User.id == OrderStatusHistory.changed_by)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
    ).all()
    return [
        OrderHistoryItem(status=h.status, changed_by_name=name, changed_by_role=role, created_at=h.created_at)
        for h, name, role in rows
    ]


def _offers(db: Session, order_id: int) -> list[OrderOfferItem]:
    rows = db.execute(
        select(OrderOffer, User.full_name)
        .join(User, User.id == OrderOffer.worker_id)
        .where(OrderOffer.order_id == order_id)
        .order_by(OrderOffer.match_score.desc().nulls_last(), OrderOffer.sent_at)
    ).all()
    return [
        OrderOfferItem(
            id=o.id,
            worker_id=o.worker_id,
            worker_name=name,
            match_score=float(o.match_score) if o.match_score is not None else None,
            distance_km=float(o.distance_km) if o.distance_km is not None else None,
            status=o.status,
            sent_at=o.sent_at,
            responded_at=o.responded_at,
        )
        for o, name in rows
    ]


def _order_detail(db: Session, order: Order) -> OrderDetail:
    order_id = order.id

    service, category_name = db.execute(
        select(Service, ServiceCategory.name)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.id == order.service_id)
    ).one()
    customer = db.get(User, order.customer_id)

    worker = None
    if order.worker_id:
        worker_user = db.get(User, order.worker_id)
        profile = db.get(WorkerProfile, order.worker_id)
        worker = OrderWorker(
            **_person(worker_user).model_dump(),
            trust_score=float(profile.trust_score) if profile else 0,
        )

    quotes = db.scalars(
        select(OrderExtraQuote).where(OrderExtraQuote.order_id == order_id).order_by(OrderExtraQuote.created_at)
    ).all()
    payments = db.scalars(
        select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)
    ).all()
    earning = db.scalar(select(WorkerEarning).where(WorkerEarning.order_id == order_id))
    review = db.scalar(select(Review).where(Review.order_id == order_id))
    complaints = db.scalars(
        select(Complaint).where(Complaint.order_id == order_id).order_by(Complaint.created_at)
    ).all()

    return OrderDetail(
        id=order.id,
        status=order.status,
        matching_mode=order.matching_mode,
        address_line=order.address_line,
        latitude=order.latitude,
        longitude=order.longitude,
        description=order.description,
        image_urls=order.image_urls or [],
        scheduled_at=order.scheduled_at,
        created_at=order.created_at,
        accepted_at=order.accepted_at,
        completed_at=order.completed_at,
        cancel_reason=order.cancel_reason,
        estimated_price=_int(order.estimated_price),
        final_price=_int(order.final_price),
        service=OrderService(
            id=service.id,
            name=service.name,
            category_name=category_name,
            base_price=int(service.base_price),
        ),
        customer=_person(customer),
        worker=worker,
        history=_history(db, order_id),
        offers=_offers(db, order_id),
        extra_quotes=[
            OrderExtraQuoteItem(
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
            OrderPaymentItem(
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
        earning=OrderEarning(
            gross_amount=int(earning.gross_amount),
            commission_amount=int(earning.commission_amount),
            net_amount=int(earning.net_amount),
        )
        if earning
        else None,
        review=OrderReview(
            rating=review.rating,
            comment=review.comment,
            is_flagged=review.is_flagged,
            flag_reason=review.flag_reason,
            created_at=review.created_at,
        )
        if review
        else None,
        complaints=[
            OrderComplaintItem(
                id=c.id,
                reason=c.reason,
                status=c.status,
                created_at=c.created_at,
                resolved_at=c.resolved_at,
            )
            for c in complaints
        ],
    )


def get_order(db: Session, order_id: int):
    return success(_order_detail(db, _get_order(db, order_id)))


# ---------- Hủy đơn ----------


def cancel_order(db: Session, admin: User, order_id: int, data: CancelOrderRequest):
    order = _get_order(db, order_id)
    if order.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Đơn đã hoàn thành hoặc đã hủy, không thể hủy nữa",
        )

    order.status = "cancelled"
    order.cancel_reason = f"[Admin] {data.reason.strip()}"
    db.add(
        OrderStatusHistory(
            order_id=order.id, status="cancelled", changed_by=admin.id, created_at=now_vn()
        )
    )

    # Offer còn đang chờ thợ phản hồi thì cho hết hạn luôn
    for offer in db.scalars(
        select(OrderOffer).where(OrderOffer.order_id == order.id, OrderOffer.status == "sent")
    ):
        offer.status = "expired"

    # Thợ đang bận vì đơn này và không còn đơn nào khác thì trả về trạng thái sẵn sàng
    if order.worker_id:
        profile = db.get(WorkerProfile, order.worker_id)
        other_active = db.scalar(
            select(func.count()).where(
                Order.worker_id == order.worker_id,
                Order.id != order.id,
                Order.status.in_(ACTIVE_STATUSES),
            )
        )
        if profile and profile.availability == "busy" and not other_active:
            profile.availability = "online"

    db.commit()
    db.refresh(order)
    return success(_order_detail(db, order), "Đã hủy đơn hàng")
