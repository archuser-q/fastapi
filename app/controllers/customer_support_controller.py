from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.controllers.customer_order_controller import get_own_order
from app.models import Complaint, Order, Review, Service, User, Warranty, WorkerProfile
from app.schemas.customer import (
    ComplaintCreate,
    ComplaintOut,
    MyReviewItem,
    ReviewCreate,
    ReviewItem,
    WarrantyClaim,
    WarrantyItem,
)
from app.services.notification_service import notify
from app.utils.dates import now_vn
from app.utils.pagination import paginate
from app.utils.response import paginated, success

REVIEW_DEADLINE_DAYS = 14
OPEN_COMPLAINT = ("open", "processing")


# ---------- Đánh giá ----------


def create_review(db: Session, customer: User, order_id: int, data: ReviewCreate):
    o = get_own_order(db, customer, order_id)
    if o.status != "completed" or o.worker_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chỉ đánh giá đơn đã hoàn thành")
    if o.completed_at and now_vn() - o.completed_at > timedelta(days=REVIEW_DEADLINE_DAYS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Đã quá {REVIEW_DEADLINE_DAYS} ngày để đánh giá")
    if db.scalar(select(Review.id).where(Review.order_id == o.id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn này đã được đánh giá")

    r = Review(
        order_id=o.id,
        customer_id=customer.id,
        worker_id=o.worker_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(r)
    profile = db.get(WorkerProfile, o.worker_id, with_for_update=True)
    if profile:
        profile.review_count += 1
    notify(db, o.worker_id, f"Bạn nhận được đánh giá {data.rating} sao", data.comment, "review", o.id)
    try:
        db.commit()
    except IntegrityError:  # 2 request đánh giá cùng lúc
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn này đã được đánh giá")
    db.refresh(r)

    # TRUST_SCORE_HOOK: tính lại trust_score của thợ o.worker_id ở đây.

    return success(
        ReviewItem(id=r.id, rating=r.rating, comment=r.comment, created_at=r.created_at),
        "Cảm ơn bạn đã đánh giá",
    )


def list_my_reviews(db: Session, customer: User, page: int, page_size: int):
    stmt = (
        select(Review, User.full_name, Service.name)
        .join(User, User.id == Review.worker_id)
        .join(Order, Order.id == Review.order_id)
        .join(Service, Service.id == Order.service_id)
        .where(Review.customer_id == customer.id)
        .order_by(Review.created_at.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        MyReviewItem(
            id=r.id,
            order_id=r.order_id,
            worker_id=r.worker_id,
            worker_name=wname,
            service_name=sname,
            rating=r.rating,
            comment=r.comment,
            created_at=r.created_at,
        )
        for r, wname, sname in rows
    ]
    return paginated(items, total, page, page_size)


# ---------- Khiếu nại ----------


def _complaint_out(c: Complaint) -> ComplaintOut:
    return ComplaintOut(
        id=c.id,
        order_id=c.order_id,
        reason=c.reason,
        description=c.description,
        status=c.status,
        resolution=c.resolution,
        created_at=c.created_at,
        resolved_at=c.resolved_at,
    )


def _ensure_no_open_complaint(db: Session, order_id: int) -> None:
    if db.scalar(
        select(Complaint.id).where(Complaint.order_id == order_id, Complaint.status.in_(OPEN_COMPLAINT))
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn đang có khiếu nại chưa xử lý xong")


def create_complaint(db: Session, customer: User, order_id: int, data: ComplaintCreate):
    o = get_own_order(db, customer, order_id)
    if o.status == "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn chưa có thợ, hãy huỷ đơn nếu cần")
    _ensure_no_open_complaint(db, o.id)

    c = Complaint(order_id=o.id, complainant_id=customer.id, reason=data.reason, description=data.description)
    db.add(c)
    db.commit()
    db.refresh(c)
    return success(_complaint_out(c), "Đã gửi khiếu nại")


def list_complaints(db: Session, customer: User, page: int, page_size: int):
    stmt = (
        select(Complaint)
        .where(Complaint.complainant_id == customer.id)
        .order_by(Complaint.created_at.desc())
    )
    rows, total = paginate(db, stmt, page, page_size)
    return paginated([_complaint_out(c) for c in rows], total, page, page_size)


# ---------- Bảo hành ----------


def _warranty_out(w: Warranty) -> WarrantyItem:
    return WarrantyItem(
        id=w.id,
        order_id=w.order_id,
        terms=w.terms,
        start_date=w.start_date,
        end_date=w.end_date,
        status=w.status,
    )


def _expire_if_needed(w: Warranty, today) -> None:
    if w.status == "active" and w.end_date < today:
        w.status = "expired"


def list_warranties(db: Session, customer: User):
    rows = db.scalars(
        select(Warranty)
        .join(Order, Order.id == Warranty.order_id)
        .where(Order.customer_id == customer.id)
        .order_by(Warranty.end_date.desc())
    ).all()
    today = now_vn().date()
    for w in rows:
        _expire_if_needed(w, today)
    db.commit()
    return success([_warranty_out(w) for w in rows])


def claim_warranty(db: Session, customer: User, warranty_id: int, data: WarrantyClaim):
    w = db.scalar(
        select(Warranty)
        .join(Order, Order.id == Warranty.order_id)
        .where(Warranty.id == warranty_id, Order.customer_id == customer.id)
        .with_for_update(of=Warranty)
    )
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy phiếu bảo hành")
    _expire_if_needed(w, now_vn().date())
    if w.status != "active":
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Phiếu bảo hành đã hết hạn hoặc đã được yêu cầu")
    _ensure_no_open_complaint(db, w.order_id)

    # Yêu cầu bảo hành được đưa vào luồng khiếu nại để admin xử lý chung
    w.status = "claimed"
    c = Complaint(
        order_id=w.order_id,
        complainant_id=customer.id,
        reason="Yêu cầu bảo hành",
        description=data.description,
    )
    db.add(c)
    o = db.get(Order, w.order_id)
    notify(db, o.worker_id, "Khách yêu cầu bảo hành", f"Đơn #{o.id}: {data.description[:80]}", "warranty", o.id)
    db.commit()
    db.refresh(c)
    return success({"warranty": _warranty_out(w), "complaint": _complaint_out(c)}, "Đã gửi yêu cầu bảo hành")
