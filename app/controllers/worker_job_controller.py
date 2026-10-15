"""App thợ: lời mời nhận đơn (offer) và toàn bộ quá trình thực hiện đơn."""

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.controllers.customer_order_controller import order_total
from app.models import (
    Complaint,
    Message,
    Order,
    OrderDispatch,
    OrderExtraQuote,
    OrderOffer,
    OrderPhoto,
    OrderStatusHistory,
    Payment,
    Review,
    Service,
    ServiceCategory,
    User,
    Warranty,
    WorkerEarning,
    WorkerProfile,
)
from app.schemas.worker_app import (
    AdvanceStatusRequest,
    ExtraQuoteCreate,
    JobCustomer,
    JobDetail,
    JobEarning,
    JobHistory,
    JobItem,
    JobPayment,
    JobPhoto,
    JobQuote,
    JobReview,
    JobWarranty,
    OfferOut,
    PhotoCreate,
    WorkerCancelRequest,
    WorkerReportCreate,
    WorkerReportOut,
)
from app.services import dispatch_service
from app.services import worker_service as ws
from app.services.matching_service import load_active_config
from app.services.notification_service import notify
from app.utils.dates import now_vn
from app.utils.pagination import paginate
from app.utils.response import paginated, success

NEXT_STATUS = {"accepted": "on_the_way", "on_the_way": "arrived", "arrived": "in_progress", "in_progress": "completed"}
NEXT_ACTION = {
    "on_the_way": "Bắt đầu di chuyển",
    "arrived": "Tôi đã đến nơi",
    "in_progress": "Bắt đầu sửa chữa",
    "completed": "Hoàn thành công việc",
}
CUSTOMER_STATUS_TEXT = {
    "on_the_way": ("Thợ đang trên đường tới", "Thợ {name} đang di chuyển tới địa chỉ của bạn."),
    "arrived": ("Thợ đã đến nơi", "Thợ {name} đã đến, bạn ra đón thợ nhé."),
    "in_progress": ("Thợ bắt đầu sửa chữa", "Thợ {name} đang kiểm tra và sửa chữa."),
    "completed": ("Đã sửa xong", "Đơn #{id} đã hoàn thành. Tổng tiền {total}. Bạn vui lòng thanh toán và đánh giá thợ nhé!"),
}
JOB_GROUPS = {
    "active": ws.OPEN_JOB_STATUSES,
    "completed": ("completed",),
    "cancelled": ("cancelled",),
    "history": ("completed", "cancelled"),
}
CHAT_STATUSES = ("accepted", "on_the_way", "arrived", "in_progress", "completed")
# Báo giá phát sinh chỉ sau khi thợ đã đến nơi xem tận mắt hiện trạng
QUOTE_STATUSES = ("arrived", "in_progress")
PHOTO_STATUSES = {"before": ("arrived", "in_progress"), "after": ("in_progress",)}
MAX_PHOTOS_PER_KIND = 6
PHONE_VISIBLE_DAYS_AFTER = 7


# =====================================================================
# Offer
# =====================================================================


def _offer_out(db: Session, offer: OrderOffer, timeout_seconds: int) -> OfferOut:
    order = db.get(Order, offer.order_id)
    sname, cname = db.execute(
        select(Service.name, ServiceCategory.name)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.id == order.service_id)
    ).one()
    customer = db.get(User, order.customer_id)
    price = int(order.estimated_price) if order.estimated_price is not None else None
    left = int((offer.expires_at - now_vn()).total_seconds()) if offer.expires_at else 0
    return OfferOut(
        id=offer.id,
        order_id=order.id,
        status=offer.status,
        round=offer.round,
        mode=offer.mode,
        sent_at=offer.sent_at,
        expires_at=offer.expires_at,
        expires_in_seconds=max(0, left),
        timeout_seconds=timeout_seconds,
        match_score=float(offer.match_score) if offer.match_score is not None else None,
        distance_km=float(offer.distance_km) if offer.distance_km is not None else None,
        service_id=order.service_id,
        service_name=sname,
        category_name=cname,
        description=order.description,
        image_urls=order.image_urls or [],
        address_line=order.address_line,
        latitude=order.latitude,
        longitude=order.longitude,
        scheduled_at=order.scheduled_at,
        estimated_price=price,
        estimated_earning=(price - ws.commission_of(price)) if price is not None else None,
        commission_rate=settings.commission_rate,
        customer_name=ws.given_name(customer.full_name if customer else None),
    )


def current_offer_out(db: Session, worker: User) -> OfferOut | None:
    offer = db.scalar(
        select(OrderOffer)
        .join(Order, Order.id == OrderOffer.order_id)
        .where(
            OrderOffer.worker_id == worker.id,
            OrderOffer.status == "sent",
            OrderOffer.expires_at > now_vn(),
            Order.status == "pending",
        )
        .order_by(OrderOffer.sent_at.desc())
        .limit(1)
    )
    if not offer:
        return None
    return _offer_out(db, offer, load_active_config(db).offer_timeout_seconds)


def current_offer(db: Session, worker: User):
    return success(current_offer_out(db, worker))


def accept_offer(db: Session, worker: User, offer_id: int):
    order = dispatch_service.accept_offer(db, worker, offer_id)
    return success(_detail(db, worker, order), "Đã nhận đơn")


def reject_offer(db: Session, worker: User, offer_id: int, reason: str | None):
    dispatch_service.reject_offer(db, worker, offer_id, reason)
    return success(message="Đã bỏ qua đơn")


# =====================================================================
# Danh sách / chi tiết đơn
# =====================================================================


def get_own_job(db: Session, worker: User, order_id: int, for_update: bool = False) -> Order:
    stmt = select(Order).where(Order.id == order_id, Order.worker_id == worker.id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn")
    return order


def job_items(db: Session, worker: User, orders: list[Order]) -> list[JobItem]:
    if not orders:
        return []
    ids = [o.id for o in orders]
    names = {
        sid: (sname, cname)
        for sid, sname, cname in db.execute(
            select(Service.id, Service.name, ServiceCategory.name)
            .join(ServiceCategory, ServiceCategory.id == Service.category_id)
            .where(Service.id.in_({o.service_id for o in orders}))
        ).all()
    }
    customers = dict(db.execute(select(User.id, User.full_name).where(User.id.in_({o.customer_id for o in orders}))).all())
    paid = dict(
        db.execute(select(Payment.order_id, Payment.method).where(Payment.order_id.in_(ids), Payment.status == "success")).all()
    )
    nets = dict(db.execute(select(WorkerEarning.order_id, WorkerEarning.net_amount).where(WorkerEarning.order_id.in_(ids))).all())
    extras = dict(
        db.execute(
            select(OrderExtraQuote.order_id, func.sum(OrderExtraQuote.amount))
            .where(OrderExtraQuote.order_id.in_(ids), OrderExtraQuote.status == "approved")
            .group_by(OrderExtraQuote.order_id)
        ).all()
    )
    ratings = dict(
        db.execute(select(Review.order_id, Review.rating).where(Review.order_id.in_(ids), Review.is_hidden.is_(False))).all()
    )
    unread = dict(
        db.execute(
            select(Message.order_id, func.count())
            .where(Message.order_id.in_(ids), Message.sender_id != worker.id, Message.is_read.is_(False))
            .group_by(Message.order_id)
        ).all()
    )
    items = []
    for o in orders:
        if o.final_price is not None:
            total = int(o.final_price)
        elif o.estimated_price is not None:
            total = int(o.estimated_price) + int(extras.get(o.id) or 0)
        else:
            total = None
        sname, cname = names.get(o.service_id, ("", ""))
        items.append(
            JobItem(
                id=o.id,
                status=o.status,
                service_name=sname,
                category_name=cname,
                address_line=o.address_line,
                latitude=o.latitude,
                longitude=o.longitude,
                scheduled_at=o.scheduled_at,
                created_at=o.created_at,
                accepted_at=o.accepted_at,
                completed_at=o.completed_at,
                estimated_price=int(o.estimated_price) if o.estimated_price is not None else None,
                final_price=int(o.final_price) if o.final_price is not None else None,
                total_amount=total,
                customer_name=customers.get(o.customer_id, "Khách hàng"),
                paid=o.id in paid,
                payment_method=paid.get(o.id),
                net_earning=int(nets[o.id]) if o.id in nets else None,
                unread_messages=unread.get(o.id, 0),
                rating=ratings.get(o.id),
            )
        )
    return items


def list_jobs(db: Session, worker: User, group: str, page: int, page_size: int):
    stmt = select(Order).where(Order.worker_id == worker.id, Order.status.in_(JOB_GROUPS[group]))
    if group == "active":
        stmt = stmt.order_by(Order.scheduled_at.asc().nulls_first(), Order.accepted_at.desc())
    else:
        stmt = stmt.order_by(func.coalesce(Order.completed_at, Order.created_at).desc(), Order.id.desc())
    orders, total = paginate(db, stmt, page, page_size)
    return paginated(job_items(db, worker, list(orders)), total, page, page_size)


def _detail(db: Session, worker: User, o: Order) -> JobDetail:
    item = job_items(db, worker, [o])[0]
    customer = db.get(User, o.customer_id)
    profile = db.get(WorkerProfile, worker.id)
    now = now_vn()

    photos = db.scalars(select(OrderPhoto).where(OrderPhoto.order_id == o.id).order_by(OrderPhoto.id)).all()
    quotes = db.scalars(
        select(OrderExtraQuote).where(OrderExtraQuote.order_id == o.id).order_by(OrderExtraQuote.created_at)
    ).all()
    payments = db.scalars(select(Payment).where(Payment.order_id == o.id).order_by(Payment.created_at)).all()
    history = db.scalars(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == o.id)
        .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
    ).all()
    review = db.scalar(select(Review).where(Review.order_id == o.id, Review.is_hidden.is_(False)))
    warranty = db.scalar(select(Warranty).where(Warranty.order_id == o.id))
    earning = db.scalar(select(WorkerEarning).where(WorkerEarning.order_id == o.id))
    open_report = db.scalar(
        select(Complaint.id).where(
            Complaint.order_id == o.id,
            Complaint.complainant_id == worker.id,
            Complaint.status.in_(("open", "processing")),
        )
    )

    phone_visible = o.status in ws.OPEN_JOB_STATUSES or (
        o.status == "completed" and o.completed_at and now - o.completed_at <= timedelta(days=PHONE_VISIBLE_DAYS_AFTER)
    )
    distance = None
    if profile and profile.current_latitude is not None:
        distance = round(_haversine(profile.current_latitude, profile.current_longitude, o.latitude, o.longitude), 2)

    nxt = NEXT_STATUS.get(o.status)
    start_at = _trip_start_at(o)
    has_after = any(p.kind == "after" for p in photos)
    pending_quote = any(q.status == "pending" for q in quotes)
    total = item.total_amount
    return JobDetail(
        **item.model_dump(),
        service_id=o.service_id,
        description=o.description,
        image_urls=o.image_urls or [],
        cancel_reason=o.cancel_reason,
        customer=JobCustomer(
            id=customer.id,
            full_name=customer.full_name,
            phone=customer.phone if phone_visible else None,
            avatar_url=customer.avatar_url,
        ),
        distance_km=distance,
        history=[JobHistory(status=h.status, created_at=h.created_at) for h in history],
        photos=[JobPhoto(id=p.id, kind=p.kind, url=p.url, created_at=p.created_at) for p in photos],
        extra_quotes=[
            JobQuote(
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
            JobPayment(
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
        review=JobReview(rating=review.rating, comment=review.comment, created_at=review.created_at) if review else None,
        warranty=JobWarranty(
            terms=warranty.terms, start_date=warranty.start_date, end_date=warranty.end_date, status=warranty.status
        )
        if warranty
        else None,
        earning=JobEarning(
            gross_amount=int(earning.gross_amount),
            commission_amount=int(earning.commission_amount),
            net_amount=int(earning.net_amount),
        )
        if earning
        else None,
        estimated_earning=(total - ws.commission_of(total)) if total is not None else None,
        next_status=nxt,
        next_action=NEXT_ACTION.get(nxt) if nxt else None,
        can_cancel=o.status in ("accepted", "on_the_way", "arrived"),
        cancel_requeues=o.status in ("accepted", "on_the_way"),
        can_quote=o.status in QUOTE_STATUSES and not pending_quote,
        can_add_photos=o.status in ("arrived", "in_progress"),
        can_confirm_cash=o.status == "completed" and not item.paid,
        can_chat=o.status in CHAT_STATUSES,
        can_report=o.status != "pending" and not open_report,
        needs_after_photo=o.status == "in_progress" and not has_after,
        needs_safety_check=o.status == "arrived",
        safety_checked_at=o.safety_checked_at,
        start_available_at=start_at if start_at and now < start_at else None,
        has_pending_quote=pending_quote,
        amount_to_collect=total if o.status == "completed" and not item.paid else None,
    )


def _trip_start_at(o: Order):
    """Đơn hẹn trước chỉ được bắt đầu di chuyển trong vòng BUSY_BEFORE_SCHEDULE_MINUTES trước giờ hẹn."""
    if o.status != "accepted" or not o.scheduled_at:
        return None
    return o.scheduled_at - timedelta(minutes=ws.BUSY_BEFORE_SCHEDULE_MINUTES)


def _haversine(lat1, lng1, lat2, lng2) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def job_detail(db: Session, worker: User, order_id: int):
    return success(_detail(db, worker, get_own_job(db, worker, order_id)))


# =====================================================================
# Cập nhật tiến độ
# =====================================================================


def advance_status(db: Session, worker: User, order_id: int, data: AdvanceStatusRequest):
    o = get_own_job(db, worker, order_id, for_update=True)
    expected = NEXT_STATUS.get(o.status)
    if expected != data.status:
        db.rollback()
        if o.status == data.status:
            raise HTTPException(status.HTTP_409_CONFLICT, "Đơn đã ở trạng thái này rồi")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không thể chuyển sang trạng thái này ở bước hiện tại")

    now = now_vn()
    extra = {}
    start_at = _trip_start_at(o)
    if data.status == "on_the_way" and start_at and now < start_at:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Đơn hẹn lúc {o.scheduled_at:%H:%M %d/%m}. Bạn có thể bắt đầu di chuyển từ {start_at:%H:%M}.",
        )
    if data.status == "in_progress":
        if not data.safety_confirmed:
            db.rollback()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Hãy xác nhận đã kiểm tra an toàn điện (ngắt nguồn, thử điện, đồ bảo hộ, báo khách) trước khi bắt đầu sửa",
            )
        o.safety_checked_at = now
    if data.status == "completed":
        if db.scalar(
            select(OrderExtraQuote.id).where(OrderExtraQuote.order_id == o.id, OrderExtraQuote.status == "pending")
        ):
            db.rollback()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Còn báo giá phát sinh chờ khách duyệt. Hãy chờ khách trả lời hoặc rút lại báo giá."
            )
        if not db.scalar(select(OrderPhoto.id).where(OrderPhoto.order_id == o.id, OrderPhoto.kind == "after")):
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cần chụp ít nhất 1 ảnh sau khi sửa để hoàn thành")
        total = order_total(db, o)
        o.final_price = total
        o.completed_at = now
        profile = db.get(WorkerProfile, worker.id, with_for_update=True)
        profile.completed_orders += 1
        if not db.scalar(select(Warranty.id).where(Warranty.order_id == o.id)):
            sname = db.scalar(select(Service.name).where(Service.id == o.service_id))
            today = now.date()
            db.add(
                Warranty(
                    order_id=o.id,
                    terms=f"Bảo hành {settings.warranty_days} ngày cho hạng mục \"{sname}\" đã sửa",
                    start_date=today,
                    end_date=today + timedelta(days=settings.warranty_days),
                )
            )
        extra["total"] = ws.money(total or 0)

    o.status = data.status
    db.add(OrderStatusHistory(order_id=o.id, status=data.status, changed_by=worker.id, created_at=now))
    ws.refresh_availability(db, worker.id)
    title, body = CUSTOMER_STATUS_TEXT[data.status]
    notify(db, o.customer_id, title, body.format(name=worker.full_name, id=o.id, **extra), "order_status", o.id)
    db.commit()
    db.refresh(o)
    msg = {
        "on_the_way": "Đã báo khách bạn đang tới",
        "arrived": "Đã báo khách bạn đã đến",
        "in_progress": "Bắt đầu sửa chữa",
        "completed": "Hoàn thành công việc! Nhớ thu tiền nếu khách trả tiền mặt",
    }[data.status]
    return success(_detail(db, worker, o), msg)


def cancel_job(db: Session, worker: User, order_id: int, data: WorkerCancelRequest):
    o = get_own_job(db, worker, order_id, for_update=True)
    if o.status in ("accepted", "on_the_way"):
        dispatch_service.requeue_after_worker_cancel(db, o, worker, data.reason)
        ws.refresh_availability(db, worker.id)
        db.commit()
        d = db.get(OrderDispatch, order_id)
        if d and d.mode == "instant":
            dispatch_service.run_instant_wave(db, order_id)
        return success({"id": order_id, "status": "pending"}, "Đã hủy nhận đơn, hệ thống sẽ tìm thợ khác cho khách")
    if o.status == "arrived":
        now = now_vn()
        o.status = "cancelled"
        o.cancel_reason = f"[Thợ] {data.reason}"
        db.add(OrderStatusHistory(order_id=o.id, status="cancelled", changed_by=worker.id, created_at=now))
        db.execute(
            update(OrderOffer)
            .where(OrderOffer.order_id == o.id, OrderOffer.worker_id == worker.id)
            .values(status="cancelled", responded_at=now, reason=data.reason)
        )
        ws.refresh_availability(db, worker.id)
        notify(db, o.customer_id, "Đơn đã bị hủy", f"Thợ đã hủy đơn #{o.id}: {data.reason}", "order_cancelled", o.id)
        db.commit()
        return success({"id": order_id, "status": "cancelled"}, "Đã hủy đơn")
    db.rollback()
    if o.status == "in_progress":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Đang sửa thì không hủy được. Nếu có vấn đề, hãy dùng Báo cáo sự cố."
        )
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn không còn hủy được")


# =====================================================================
# Ảnh trước / sau
# =====================================================================


def add_photos(db: Session, worker: User, order_id: int, data: PhotoCreate):
    o = get_own_job(db, worker, order_id)
    if o.status not in PHOTO_STATUSES[data.kind]:
        label = "trước khi sửa" if data.kind == "before" else "sau khi sửa"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Chưa thể thêm ảnh {label} ở bước này")
    if any(not u.startswith(("http://", "https://")) for u in data.urls):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đường dẫn ảnh không hợp lệ")
    count = db.scalar(
        select(func.count()).select_from(OrderPhoto).where(OrderPhoto.order_id == o.id, OrderPhoto.kind == data.kind)
    )
    if count + len(data.urls) > MAX_PHOTOS_PER_KIND:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tối đa {MAX_PHOTOS_PER_KIND} ảnh mỗi loại")
    db.add_all([OrderPhoto(order_id=o.id, uploader_id=worker.id, kind=data.kind, url=u) for u in data.urls])
    db.commit()
    return success(_detail(db, worker, o), "Đã lưu ảnh")


def delete_photo(db: Session, worker: User, order_id: int, photo_id: int):
    o = get_own_job(db, worker, order_id)
    photo = db.get(OrderPhoto, photo_id)
    if not photo or photo.order_id != o.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh")
    if o.status in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn đã đóng, không xóa được ảnh")
    db.delete(photo)
    db.commit()
    return success(_detail(db, worker, o), "Đã xóa ảnh")


# =====================================================================
# Báo giá phát sinh
# =====================================================================


def create_quote(db: Session, worker: User, order_id: int, data: ExtraQuoteCreate):
    o = get_own_job(db, worker, order_id, for_update=True)
    if o.status not in QUOTE_STATUSES:
        db.rollback()
        if o.status in ("accepted", "on_the_way"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hãy đến nơi xem hiện trạng rồi mới báo giá phát sinh")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn không còn nhận báo giá phát sinh")
    if db.scalar(select(OrderExtraQuote.id).where(OrderExtraQuote.order_id == o.id, OrderExtraQuote.status == "pending")):
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đang có 1 báo giá chờ khách duyệt")
    db.add(OrderExtraQuote(order_id=o.id, worker_id=worker.id, description=data.description, amount=data.amount))
    notify(
        db,
        o.customer_id,
        "Thợ gửi báo giá phát sinh",
        f"Đơn #{o.id}: {data.description} — {ws.money(data.amount)}. Vui lòng xác nhận để thợ tiếp tục.",
        "extra_quote",
        o.id,
    )
    db.commit()
    return success(_detail(db, worker, o), "Đã gửi báo giá, chờ khách xác nhận")


def cancel_quote(db: Session, worker: User, order_id: int, quote_id: int):
    o = get_own_job(db, worker, order_id)
    q = db.scalar(
        select(OrderExtraQuote)
        .where(OrderExtraQuote.id == quote_id, OrderExtraQuote.order_id == o.id)
        .with_for_update()
    )
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy báo giá")
    if q.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Khách đã trả lời báo giá này")
    q.status, q.responded_at = "cancelled", now_vn()
    notify(db, o.customer_id, "Thợ đã rút lại báo giá phát sinh", f"Đơn #{o.id}: {q.description}", "extra_quote", o.id)
    db.commit()
    return success(_detail(db, worker, o), "Đã rút lại báo giá")


# =====================================================================
# Thu tiền mặt
# =====================================================================


def confirm_cash(db: Session, worker: User, order_id: int):
    o = get_own_job(db, worker, order_id, for_update=True)
    if o.status != "completed":
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chỉ xác nhận thu tiền khi đơn đã hoàn thành")
    if db.scalar(select(Payment.id).where(Payment.order_id == o.id, Payment.status == "success")):
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn đã được thanh toán")
    now = now_vn()
    amount = order_total(db, o) or 0
    pending = db.scalars(select(Payment).where(Payment.order_id == o.id, Payment.status == "pending")).all()
    cash = next((p for p in pending if p.method == "cash"), None)
    for p in pending:
        if p is not cash:
            p.status = "failed"  # khách đã chọn ví nhưng cuối cùng trả tiền mặt
    if cash is None:
        cash = Payment(order_id=o.id, amount=amount, method="cash", status="success", paid_at=now)
        db.add(cash)
    else:
        cash.status, cash.paid_at, cash.amount = "success", now, amount
    db.flush()
    ws.record_paid_order(db, o, cash)
    notify(db, o.customer_id, "Thợ đã xác nhận nhận tiền mặt", f"Đơn #{o.id}: {ws.money(amount)}. Cảm ơn bạn!", "payment", o.id)
    db.commit()
    return success(_detail(db, worker, o), f"Đã xác nhận thu {ws.money(amount)} tiền mặt")


# =====================================================================
# Báo cáo sự cố (đi vào luồng khiếu nại của admin)
# =====================================================================


def _report_out(c: Complaint) -> WorkerReportOut:
    return WorkerReportOut(
        id=c.id,
        order_id=c.order_id,
        reason=c.reason,
        description=c.description,
        status=c.status,
        resolution=c.resolution,
        created_at=c.created_at,
        resolved_at=c.resolved_at,
    )


def create_report(db: Session, worker: User, order_id: int, data: WorkerReportCreate):
    o = get_own_job(db, worker, order_id)
    if db.scalar(
        select(Complaint.id).where(
            Complaint.order_id == o.id,
            Complaint.complainant_id == worker.id,
            Complaint.status.in_(("open", "processing")),
        )
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bạn đã báo cáo đơn này, đang chờ xử lý")
    c = Complaint(order_id=o.id, complainant_id=worker.id, reason=f"[Thợ báo cáo] {data.reason}", description=data.description)
    db.add(c)
    db.commit()
    db.refresh(c)
    return success(_report_out(c), "Đã gửi báo cáo, bộ phận hỗ trợ sẽ liên hệ bạn")


def list_reports(db: Session, worker: User, page: int, page_size: int):
    stmt = select(Complaint).where(Complaint.complainant_id == worker.id).order_by(Complaint.created_at.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return paginated([_report_out(c) for c in rows], total, page, page_size)
