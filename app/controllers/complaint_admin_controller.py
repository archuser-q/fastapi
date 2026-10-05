from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Complaint,
    Notification,
    Order,
    Review,
    Service,
    ServiceCategory,
    User,
)
from app.schemas.complaint_admin import (
    ComplaintDetail,
    ComplaintHistoryStats,
    ComplaintListItem,
    ComplaintOrder,
    ComplaintOrderReview,
    ComplaintPerson,
    ComplaintStatusCounts,
    ComplaintStatusUpdate,
    StatusCount,
)
from app.utils.dates import now_vn
from app.utils.response import paginated, success

COMPLAINT_STATUSES = ("open", "processing", "resolved", "rejected")

# Trạng thái hiện tại -> các trạng thái được phép chuyển sang
ALLOWED_TRANSITIONS = {
    "open": {"processing", "resolved", "rejected"},
    "processing": {"resolved", "rejected"},
    "resolved": set(),
    "rejected": set(),
}

NOTIFY_TITLES = {
    "processing": "Khiếu nại của bạn đang được xử lý",
    "resolved": "Khiếu nại của bạn đã được giải quyết",
    "rejected": "Khiếu nại của bạn không được chấp nhận",
}


def _person(user: User | None) -> ComplaintPerson | None:
    if user is None:
        return None
    return ComplaintPerson(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        role=user.role,
        avatar_url=user.avatar_url,
    )


# ---------- Bộ lọc dùng chung cho danh sách và số đếm ----------


def _base_query(stmt, complainant, worker, handler):
    return (
        stmt.select_from(Complaint)
        .join(complainant, complainant.id == Complaint.complainant_id)
        .join(Order, Order.id == Complaint.order_id)
        .join(Service, Service.id == Order.service_id)
        .outerjoin(worker, worker.id == Order.worker_id)
        .outerjoin(handler, handler.id == Complaint.handled_by)
    )


def _filters(complainant, worker, keyword, date_from: date | None, date_to: date | None):
    conditions = []
    if keyword:
        text = keyword.strip()
        if text.startswith("#") and text[1:].isdigit():
            # "#123" là tìm theo mã đơn hàng bị khiếu nại
            conditions.append(Complaint.order_id == int(text[1:]))
        else:
            like = f"%{text}%"
            conditions.append(
                or_(
                    Complaint.reason.ilike(like),
                    Complaint.description.ilike(like),
                    complainant.full_name.ilike(like),
                    complainant.phone.ilike(like),
                    worker.full_name.ilike(like),
                )
            )
    if date_from:
        conditions.append(Complaint.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(
            Complaint.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    return conditions


def list_complaints(db: Session, complaint_status, keyword, date_from, date_to, page, page_size):
    complainant, worker, handler = aliased(User), aliased(User), aliased(User)
    stmt = _base_query(
        select(Complaint, complainant, worker.full_name, Service.name, handler.full_name),
        complainant,
        worker,
        handler,
    ).where(*_filters(complainant, worker, keyword, date_from, date_to))
    if complaint_status:
        stmt = stmt.where(Complaint.status == complaint_status)

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    # Khiếu nại mới nhất lên đầu; ở tab "Mới", cái chờ lâu nhất lên đầu để xử lý trước
    order_by = (
        [Complaint.created_at.asc()]
        if complaint_status in ("open", "processing")
        else [Complaint.created_at.desc()]
    )
    rows = db.execute(
        stmt.order_by(*order_by, Complaint.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = [
        ComplaintListItem(
            id=c.id,
            order_id=c.order_id,
            reason=c.reason,
            status=c.status,
            complainant=_person(person),
            worker_name=worker_name,
            service_name=service_name,
            handled_by_name=handler_name,
            created_at=c.created_at,
            resolved_at=c.resolved_at,
        )
        for c, person, worker_name, service_name, handler_name in rows
    ]
    return paginated(items, total, page, page_size)


def get_status_counts(db: Session, keyword, date_from, date_to):
    complainant, worker, handler = aliased(User), aliased(User), aliased(User)
    rows = db.execute(
        _base_query(select(Complaint.status, func.count()), complainant, worker, handler)
        .where(*_filters(complainant, worker, keyword, date_from, date_to))
        .group_by(Complaint.status)
    ).all()
    counts = dict(rows)
    return success(
        ComplaintStatusCounts(
            total=sum(counts.values()),
            items=[StatusCount(status=s, count=counts.get(s, 0)) for s in COMPLAINT_STATUSES],
        )
    )


# ---------- Chi tiết ----------


def _get_complaint(db: Session, complaint_id: int) -> Complaint:
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy khiếu nại")
    return complaint


def _complaint_detail(db: Session, complaint: Complaint) -> ComplaintDetail:
    order = db.get(Order, complaint.order_id)
    service_name, category_name = db.execute(
        select(Service.name, ServiceCategory.name)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.id == order.service_id)
    ).one()
    customer = db.get(User, order.customer_id)
    worker = db.get(User, order.worker_id) if order.worker_id else None
    review = db.scalar(select(Review).where(Review.order_id == order.id))

    worker_total, worker_resolved = (0, 0)
    if order.worker_id:
        worker_total, worker_resolved = db.execute(
            select(func.count(), func.count().filter(Complaint.status == "resolved"))
            .select_from(Complaint)
            .join(Order, Order.id == Complaint.order_id)
            .where(Order.worker_id == order.worker_id)
        ).one()
    complainant_total = db.scalar(
        select(func.count(Complaint.id)).where(Complaint.complainant_id == complaint.complainant_id)
    )

    price = order.final_price if order.final_price is not None else order.estimated_price
    return ComplaintDetail(
        id=complaint.id,
        reason=complaint.reason,
        description=complaint.description,
        status=complaint.status,
        resolution=complaint.resolution,
        created_at=complaint.created_at,
        resolved_at=complaint.resolved_at,
        complainant=_person(db.get(User, complaint.complainant_id)),
        handled_by=_person(db.get(User, complaint.handled_by)) if complaint.handled_by else None,
        order=ComplaintOrder(
            id=order.id,
            status=order.status,
            service_name=service_name,
            category_name=category_name,
            amount=int(price) if price is not None else None,
            address_line=order.address_line,
            customer=_person(customer),
            worker=_person(worker),
            created_at=order.created_at,
            completed_at=order.completed_at,
        ),
        review=ComplaintOrderReview(rating=review.rating, comment=review.comment) if review else None,
        history=ComplaintHistoryStats(
            worker_total=worker_total,
            worker_resolved=worker_resolved,
            complainant_total=complainant_total,
        ),
    )


def get_complaint(db: Session, complaint_id: int):
    return success(_complaint_detail(db, _get_complaint(db, complaint_id)))


# ---------- Cập nhật trạng thái ----------


def update_status(db: Session, admin: User, complaint_id: int, data: ComplaintStatusUpdate):
    complaint = _get_complaint(db, complaint_id)
    if data.status not in ALLOWED_TRANSITIONS[complaint.status]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Khiếu nại đã đóng, không thể cập nhật nữa"
            if complaint.status in ("resolved", "rejected")
            else "Khiếu nại đang được xử lý rồi",
        )

    complaint.status = data.status
    complaint.handled_by = admin.id
    if data.status in ("resolved", "rejected"):
        complaint.resolution = data.resolution.strip()
        complaint.resolved_at = now_vn()

    # Báo cho người gửi khiếu nại biết trên ứng dụng
    db.add(
        Notification(
            user_id=complaint.complainant_id,
            title=NOTIFY_TITLES[data.status],
            body=complaint.resolution
            if data.status != "processing"
            else f"Đơn #{complaint.order_id}: {complaint.reason}",
            type="complaint",
            reference_id=complaint.id,
            created_at=now_vn(),
        )
    )
    db.commit()
    db.refresh(complaint)

    messages = {
        "processing": "Đã tiếp nhận khiếu nại",
        "resolved": "Đã giải quyết khiếu nại",
        "rejected": "Đã từ chối khiếu nại",
    }
    return success(_complaint_detail(db, complaint), messages[data.status])
