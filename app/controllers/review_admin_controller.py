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
    WorkerProfile,
)
from app.schemas.review_admin import (
    RatingBucket,
    ReviewComplaint,
    ReviewDetail,
    ReviewListItem,
    ReviewModeration,
    ReviewOrder,
    ReviewPerson,
    ReviewStats,
    ReviewWorkerStats,
)
from app.utils.dates import now_vn
from app.utils.response import paginated, success

LOW_RATING = 2  # Đánh giá từ 2 sao trở xuống được coi là đánh giá thấp


def _person(user: User) -> ReviewPerson:
    return ReviewPerson(
        id=user.id, full_name=user.full_name, phone=user.phone, avatar_url=user.avatar_url
    )


def _ratio(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0


# ---------- Bộ lọc dùng chung cho danh sách và thống kê ----------


def _base_query(stmt, customer, worker):
    return (
        stmt.select_from(Review)
        .join(customer, customer.id == Review.customer_id)
        .join(worker, worker.id == Review.worker_id)
        .join(Order, Order.id == Review.order_id)
        .join(Service, Service.id == Order.service_id)
    )


def _filters(customer, worker, keyword, worker_id, date_from: date | None, date_to: date | None):
    conditions = []
    if keyword:
        text = keyword.strip()
        if text.startswith("#") and text[1:].isdigit():
            # "#123" là tìm theo mã đơn hàng
            conditions.append(Review.order_id == int(text[1:]))
        else:
            like = f"%{text}%"
            conditions.append(
                or_(
                    Review.comment.ilike(like),
                    customer.full_name.ilike(like),
                    worker.full_name.ilike(like),
                    worker.phone.ilike(like),
                )
            )
    if worker_id:
        conditions.append(Review.worker_id == worker_id)
    if date_from:
        conditions.append(Review.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(Review.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    return conditions


def _to_item(review: Review, customer: User, worker: User, service_name: str) -> ReviewListItem:
    return ReviewListItem(
        id=review.id,
        order_id=review.order_id,
        rating=review.rating,
        comment=review.comment,
        is_flagged=review.is_flagged,
        flag_reason=review.flag_reason,
        is_hidden=review.is_hidden,
        customer=_person(customer),
        worker=_person(worker),
        service_name=service_name,
        created_at=review.created_at,
        moderated_at=review.moderated_at,
    )


def list_reviews(
    db: Session, view, rating, keyword, worker_id, date_from, date_to, sort, page, page_size
):
    customer, worker = aliased(User), aliased(User)
    stmt = _base_query(select(Review, customer, worker, Service.name), customer, worker).where(
        *_filters(customer, worker, keyword, worker_id, date_from, date_to)
    )

    if view == "flagged":
        stmt = stmt.where(Review.is_flagged.is_(True), Review.is_hidden.is_(False))
    elif view == "low":
        stmt = stmt.where(Review.rating <= LOW_RATING, Review.is_hidden.is_(False))
    elif view == "hidden":
        stmt = stmt.where(Review.is_hidden.is_(True))
    if rating:
        stmt = stmt.where(Review.rating == rating)

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order_by = (
        [Review.rating.asc(), Review.created_at.desc()]
        if sort == "lowest"
        else [Review.created_at.desc()]
    )
    rows = db.execute(
        stmt.order_by(*order_by, Review.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return paginated([_to_item(*row) for row in rows], total, page, page_size)


def get_stats(db: Session, keyword, worker_id, date_from, date_to):
    customer, worker = aliased(User), aliased(User)
    visible = Review.is_hidden.is_(False)
    conditions = _filters(customer, worker, keyword, worker_id, date_from, date_to)

    total, visible_count, flagged, hidden, low, average = db.execute(
        _base_query(
            select(
                func.count(),
                func.count().filter(visible),
                func.count().filter(Review.is_flagged.is_(True), visible),
                func.count().filter(Review.is_hidden.is_(True)),
                func.count().filter(Review.rating <= LOW_RATING, visible),
                func.avg(Review.rating).filter(visible),
            ),
            customer,
            worker,
        ).where(*conditions)
    ).one()

    stars = dict(
        db.execute(
            _base_query(select(Review.rating, func.count()), customer, worker)
            .where(*conditions, visible)
            .group_by(Review.rating)
        ).all()
    )
    return success(
        ReviewStats(
            total=total,
            visible=visible_count,
            flagged=flagged,
            hidden=hidden,
            low=low,
            average=round(float(average), 2) if average is not None else None,
            distribution=[
                RatingBucket(
                    star=s, count=stars.get(s, 0), percent=_ratio(stars.get(s, 0), visible_count)
                )
                for s in range(5, 0, -1)
            ],
        )
    )


# ---------- Chi tiết ----------


def _get_review(db: Session, review_id: int) -> Review:
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đánh giá")
    return review


def _review_detail(db: Session, review: Review) -> ReviewDetail:
    order = db.get(Order, review.order_id)
    service_name, category_name = db.execute(
        select(Service.name, ServiceCategory.name)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(Service.id == order.service_id)
    ).one()
    customer = db.get(User, review.customer_id)
    worker = db.get(User, review.worker_id)
    moderator = db.get(User, review.moderated_by) if review.moderated_by else None

    visible = Review.is_hidden.is_(False)
    average, visible_count, low, flagged, hidden = db.execute(
        select(
            func.avg(Review.rating).filter(visible),
            func.count().filter(visible),
            func.count().filter(visible, Review.rating <= LOW_RATING),
            func.count().filter(visible, Review.is_flagged.is_(True)),
            func.count().filter(Review.is_hidden.is_(True)),
        ).where(Review.worker_id == review.worker_id)
    ).one()

    complaints = db.scalars(
        select(Complaint).where(Complaint.order_id == order.id).order_by(Complaint.created_at)
    ).all()
    price = order.final_price if order.final_price is not None else order.estimated_price

    return ReviewDetail(
        **_to_item(review, customer, worker, service_name).model_dump(),
        moderation_note=review.moderation_note,
        moderated_by_name=moderator.full_name if moderator else None,
        order=ReviewOrder(
            id=order.id,
            status=order.status,
            service_name=service_name,
            category_name=category_name,
            amount=int(price) if price is not None else None,
            completed_at=order.completed_at,
        ),
        worker_stats=ReviewWorkerStats(
            average=round(float(average), 2) if average is not None else None,
            visible_reviews=visible_count,
            low_reviews=low,
            flagged_reviews=flagged,
            hidden_reviews=hidden,
        ),
        complaints=[
            ReviewComplaint(id=c.id, reason=c.reason, status=c.status, created_at=c.created_at)
            for c in complaints
        ],
    )


def get_review(db: Session, review_id: int):
    return success(_review_detail(db, _get_review(db, review_id)))


# ---------- Kiểm duyệt ----------


def _sync_worker_review_count(db: Session, worker_id: int) -> None:
    """Số đánh giá của thợ chỉ tính các đánh giá đang hiển thị."""
    profile = db.get(WorkerProfile, worker_id)
    if profile:
        profile.review_count = db.scalar(
            select(func.count(Review.id)).where(
                Review.worker_id == worker_id, Review.is_hidden.is_(False)
            )
        )


def moderate_review(db: Session, admin: User, review_id: int, data: ReviewModeration):
    review = _get_review(db, review_id)
    note = (data.note or "").strip() or None

    if data.action == "flag":
        if review.is_hidden:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đánh giá đã bị ẩn")
        if review.is_flagged:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đánh giá đã được gắn cờ")
        review.is_flagged = True
        review.flag_reason = note[:255]
    elif data.action == "approve":
        if not review.is_flagged or review.is_hidden:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Chỉ giữ lại được đánh giá đang bị gắn cờ"
            )
        review.is_flagged = False
    elif data.action == "hide":
        if review.is_hidden:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đánh giá đã bị ẩn")
        review.is_hidden = True
        review.is_flagged = False
    elif data.action == "restore":
        if not review.is_hidden:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đánh giá đang hiển thị")
        review.is_hidden = False

    review.moderated_by = admin.id
    review.moderated_at = now_vn()
    if note or data.action in ("approve", "restore"):
        review.moderation_note = note

    if data.action in ("hide", "restore"):
        db.flush()
        _sync_worker_review_count(db, review.worker_id)

    if data.action == "hide":
        db.add(
            Notification(
                user_id=review.customer_id,
                title="Đánh giá của bạn đã bị ẩn",
                body=f"Đánh giá cho đơn #{review.order_id} vi phạm quy định: {note}",
                type="review",
                reference_id=review.id,
                created_at=now_vn(),
            )
        )

    db.commit()
    db.refresh(review)
    messages = {
        "flag": "Đã gắn cờ đánh giá",
        "approve": "Đã giữ lại đánh giá",
        "hide": "Đã ẩn đánh giá",
        "restore": "Đã hiển thị lại đánh giá",
    }
    return success(_review_detail(db, review), messages[data.action])
