from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Complaint,
    Order,
    OrderStatusHistory,
    Review,
    Service,
    ServiceCategory,
    User,
    WorkerDocument,
    WorkerProfile,
)
from app.schemas.admin import (
    AdminWorkerDetail,
    AdminWorkerItem,
    DashboardOverview,
    DashboardStats,
    GrowthStat,
    MonthlyPoint,
    OnlineWorkersStat,
    RecentComplaint,
    RecentComplaints,
    RecentOrder,
    ReviewDocumentRequest,
    SatisfactionStat,
    ServiceShare,
    TopWorker,
    UserStatusUpdate,
    WorkerActivity,
    WorkerVerificationRequest,
)
from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut, WorkerProfileOut
from app.utils.pagination import paginate
from app.utils.response import paginated, success

REQUIRED_DOCS = {"id_card_front", "id_card_back", "portrait"}

def list_users(db: Session, role, user_status, keyword, page, page_size):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if user_status:
        stmt = stmt.where(User.status == user_status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(User.full_name.ilike(like), User.phone.ilike(like), User.email.ilike(like))
        )
    stmt = stmt.order_by(User.id.desc())

    users, total = paginate(db, stmt, page, page_size)
    items = [UserOut.model_validate(u) for u in users]
    return paginated(items, total, page, page_size)


def get_user(db: Session, user_id: int):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng")
    return success(UserOut.model_validate(user))


def update_user_status(db: Session, admin: User, user_id: int, data: UserStatusUpdate):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng")
    if user.id == admin.id or user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không thể thay đổi trạng thái tài khoản admin")

    user.status = data.status
    if data.status == "blocked" and user.role == "worker":
        profile = db.get(WorkerProfile, user.id)
        if profile:
            profile.availability = "offline"

    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Cập nhật trạng thái thành công")


def list_workers(db: Session, verification_status, page, page_size):
    stmt = select(User).join(WorkerProfile, WorkerProfile.user_id == User.id)
    if verification_status:
        stmt = stmt.where(WorkerProfile.verification_status == verification_status)
    stmt = stmt.order_by(User.id.desc())

    users, total = paginate(db, stmt, page, page_size)
    profiles = {
        p.user_id: p
        for p in db.scalars(
            select(WorkerProfile).where(WorkerProfile.user_id.in_([u.id for u in users]))
        )
    }
    items = [
        AdminWorkerItem(
            user=UserOut.model_validate(u),
            profile=WorkerProfileOut.model_validate(profiles[u.id]),
        )
        for u in users
    ]
    return paginated(items, total, page, page_size)


def get_worker(db: Session, worker_id: int):
    user = db.get(User, worker_id)
    profile = db.get(WorkerProfile, worker_id)
    if not user or not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thợ")

    documents = db.scalars(
        select(WorkerDocument)
        .where(WorkerDocument.worker_id == worker_id)
        .order_by(WorkerDocument.uploaded_at.desc())
    ).all()
    detail = AdminWorkerDetail(
        user=UserOut.model_validate(user),
        profile=WorkerProfileOut.model_validate(profile),
        documents=[WorkerDocumentOut.model_validate(d) for d in documents],
    )
    return success(detail)


def review_document(db: Session, reviewer: User, document_id: int, data: ReviewDocumentRequest):
    doc = db.get(WorkerDocument, document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy giấy tờ")

    doc.status = data.status
    doc.reject_reason = data.reject_reason if data.status == "rejected" else None
    doc.reviewed_by = reviewer.id
    doc.reviewed_at = func.now()
    db.commit()
    db.refresh(doc)
    return success(WorkerDocumentOut.model_validate(doc), "Đã cập nhật giấy tờ")


def update_worker_verification(db: Session, worker_id: int, data: WorkerVerificationRequest):
    profile = db.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thợ")

    if data.status == "approved":
        approved = set(
            db.scalars(
                select(WorkerDocument.doc_type).where(
                    WorkerDocument.worker_id == worker_id,
                    WorkerDocument.status == "approved",
                )
            )
        )
        missing = REQUIRED_DOCS - approved
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Chưa duyệt đủ giấy tờ bắt buộc: " + ", ".join(sorted(missing)),
            )

    profile.verification_status = data.status
    if data.status != "approved":
        profile.availability = "offline"

    db.commit()
    db.refresh(profile)
    return success(WorkerProfileOut.model_validate(profile), "Đã cập nhật xác minh thợ")


# ---------- Dashboard (trang Overview) ----------

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

ACTIVITY_ACTIONS = {
    "accepted": "đã nhận đơn",
    "on_the_way": "đang trên đường đến",
    "arrived": "đã đến nơi",
    "in_progress": "bắt đầu thực hiện",
    "completed": "đã hoàn thành đơn",
}


def _now() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(d: datetime) -> datetime:
    return _day_start(d).replace(day=1)


def _add_months(d: datetime, n: int) -> datetime:
    total = d.year * 12 + d.month - 1 + n
    return d.replace(year=total // 12, month=total % 12 + 1, day=1)


def _prev_window(now: datetime, cur_start: datetime, prev_start: datetime):
    return prev_start, min(prev_start + (now - cur_start), cur_start)


def _percent(cur, prev) -> float | None:
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _growth(cur: int, prev: int) -> GrowthStat:
    return GrowthStat(value=cur, previous=prev, change_percent=_percent(cur, prev))


def _revenue(db: Session, start: datetime, end: datetime) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Order.final_price), 0)).where(
            Order.status == "completed",
            Order.completed_at >= start,
            Order.completed_at < end,
        )
    )
    return int(total)


def _order_count(db: Session, start: datetime, end: datetime) -> int:
    return db.scalar(
        select(func.count(Order.id)).where(Order.created_at >= start, Order.created_at < end)
    )


def _rating(db: Session, start: datetime, end: datetime):
    avg, count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.created_at >= start, Review.created_at < end
        )
    ).one()
    return (round(float(avg), 2) if avg is not None else None), count


def _stats(db: Session, now: datetime) -> DashboardStats:
    month_start = _month_start(now)
    next_month = _add_months(month_start, 1)
    prev_month = _add_months(month_start, -1)
    pm_start, pm_end = _prev_window(now, month_start, prev_month)

    revenue = _growth(
        _revenue(db, month_start, next_month),
        _revenue(db, pm_start, pm_end),
    )

    today = _day_start(now)
    yesterday = today - timedelta(days=1)
    y_start, y_end = _prev_window(now, today, yesterday)
    orders_today = _growth(
        _order_count(db, today, today + timedelta(days=1)),
        _order_count(db, y_start, y_end),
    )

    rows = db.execute(
        select(WorkerProfile.availability, func.count())
        .join(User, User.id == WorkerProfile.user_id)
        .where(User.status == "active", WorkerProfile.verification_status == "approved")
        .group_by(WorkerProfile.availability)
    ).all()
    counts = dict(rows)
    online_workers = OnlineWorkersStat(
        online=counts.get("online", 0),
        busy=counts.get("busy", 0),
        total_approved=sum(counts.values()),
    )

    score, review_count = _rating(db, month_start, next_month)
    prev_score, _ = _rating(db, prev_month, month_start)
    satisfaction = SatisfactionStat(
        score=score,
        previous=prev_score,
        change=round(score - prev_score, 2) if score is not None and prev_score is not None else None,
        review_count=review_count,
    )

    return DashboardStats(
        revenue_month=revenue,
        orders_today=orders_today,
        online_workers=online_workers,
        satisfaction=satisfaction,
    )


def _revenue_chart(db: Session, now: datetime, months: int) -> list[MonthlyPoint]:
    this_month = _month_start(now)
    first = _add_months(this_month, -(months - 1))

    bucket = func.date_trunc("month", Order.completed_at)
    rows = db.execute(
        select(bucket, func.coalesce(func.sum(Order.final_price), 0), func.count(Order.id))
        .where(Order.status == "completed", Order.completed_at >= first)
        .group_by(bucket)
    ).all()
    data = {r[0]: (int(r[1]), r[2]) for r in rows}

    points = []
    for i in range(months):
        m = _add_months(first, i)
        revenue, orders = data.get(m, (0, 0))
        points.append(
            MonthlyPoint(
                month=m.strftime("%Y-%m"),
                label=f"T{m.month}",
                revenue=revenue,
                orders=orders,
            )
        )
    return points


def _service_breakdown(db: Session, now: datetime) -> list[ServiceShare]:
    cat = aliased(ServiceCategory)
    top = aliased(ServiceCategory)
    count = func.count(Order.id)

    rows = db.execute(
        select(top.id, top.name, count)
        .select_from(Order)
        .join(Service, Service.id == Order.service_id)
        .join(cat, cat.id == Service.category_id)
        .join(top, top.id == func.coalesce(cat.parent_id, cat.id))
        .where(Order.created_at >= _month_start(now), Order.status != "cancelled")
        .group_by(top.id, top.name)
        .order_by(count.desc())
    ).all()

    total = sum(r[2] for r in rows)
    return [
        ServiceShare(
            category_id=r[0],
            name=r[1],
            orders=r[2],
            percent=round(r[2] / total * 100, 1) if total else 0,
        )
        for r in rows
    ]


def _worker_activities(db: Session, now: datetime, limit: int) -> list[WorkerActivity]:
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            User.avatar_url,
            Order.id.label("order_id"),
            OrderStatusHistory.status,
            OrderStatusHistory.created_at,
        )
        .select_from(OrderStatusHistory)
        .join(Order, Order.id == OrderStatusHistory.order_id)
        .join(User, User.id == Order.worker_id)
        .where(
            OrderStatusHistory.created_at >= _day_start(now),
            OrderStatusHistory.status.in_(ACTIVITY_ACTIONS.keys()),
        )
        .order_by(OrderStatusHistory.created_at.desc(), OrderStatusHistory.id.desc())
        .limit(limit)
    ).all()

    return [
        WorkerActivity(
            worker_id=r[0],
            worker_name=r[1],
            avatar_url=r[2],
            order_id=r.order_id,
            status=r.status,
            action=ACTIVITY_ACTIONS[r.status],
            created_at=r.created_at,
        )
        for r in rows
    ]


def _top_workers(db: Session, limit: int) -> list[TopWorker]:
    ratings = (
        select(Review.worker_id, func.avg(Review.rating).label("avg_rating"))
        .group_by(Review.worker_id)
        .subquery()
    )
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            User.avatar_url,
            WorkerProfile.trust_score,
            WorkerProfile.review_count,
            WorkerProfile.completed_orders,
            ratings.c.avg_rating,
        )
        .select_from(User)
        .join(WorkerProfile, WorkerProfile.user_id == User.id)
        .outerjoin(ratings, ratings.c.worker_id == WorkerProfile.user_id)
        .where(
            User.status == "active",
            WorkerProfile.verification_status == "approved",
            WorkerProfile.review_count > 0,
        )
        .order_by(WorkerProfile.trust_score.desc(), WorkerProfile.completed_orders.desc())
        .limit(limit)
    ).all()

    return [
        TopWorker(
            user_id=r[0],
            full_name=r[1],
            avatar_url=r[2],
            trust_score=float(r[3]),
            review_count=r[4],
            completed_orders=r[5],
            avg_rating=round(float(r[6]), 2) if r[6] is not None else None,
        )
        for r in rows
    ]


def _recent_complaints(db: Session, limit: int) -> RecentComplaints:
    total_open = db.scalar(select(func.count(Complaint.id)).where(Complaint.status == "open"))
    rows = db.execute(
        select(
            Complaint.id,
            Complaint.order_id,
            User.full_name,
            Complaint.reason,
            Complaint.status,
            Complaint.created_at,
        )
        .join(User, User.id == Complaint.complainant_id)
        .where(Complaint.status == "open")
        .order_by(Complaint.created_at.desc())
        .limit(limit)
    ).all()

    items = [
        RecentComplaint(
            id=r[0],
            order_id=r[1],
            complainant_name=r[2],
            reason=r[3],
            status=r[4],
            created_at=r[5],
        )
        for r in rows
    ]
    return RecentComplaints(total_open=total_open, items=items)


def _recent_orders(db: Session, limit: int) -> list[RecentOrder]:
    customer = aliased(User)
    worker = aliased(User)
    rows = db.execute(
        select(
            Order.id,
            Order.status,
            Order.final_price,
            Order.estimated_price,
            Order.created_at,
            Service.name.label("service_name"),
            customer.full_name.label("customer_name"),
            worker.full_name.label("worker_name"),
        )
        .select_from(Order)
        .join(Service, Service.id == Order.service_id)
        .join(customer, customer.id == Order.customer_id)
        .outerjoin(worker, worker.id == Order.worker_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    ).all()

    items = []
    for r in rows:
        price = r.final_price if r.final_price is not None else r.estimated_price
        items.append(
            RecentOrder(
                id=r.id,
                customer_name=r.customer_name,
                worker_name=r.worker_name,
                service_name=r.service_name,
                status=r.status,
                amount=int(price) if price is not None else None,
                created_at=r.created_at,
            )
        )
    return items


def get_dashboard_stats(db: Session):
    return success(_stats(db, _now()))


def get_dashboard_revenue_chart(db: Session, months: int):
    return success(_revenue_chart(db, _now(), months))


def get_dashboard_service_breakdown(db: Session):
    return success(_service_breakdown(db, _now()))


def get_dashboard_worker_activities(db: Session, limit: int):
    return success(_worker_activities(db, _now(), limit))


def get_dashboard_top_workers(db: Session, limit: int):
    return success(_top_workers(db, limit))


def get_dashboard_recent_complaints(db: Session, limit: int):
    return success(_recent_complaints(db, limit))


def get_dashboard_recent_orders(db: Session, limit: int):
    return success(_recent_orders(db, limit))


def get_dashboard_overview(db: Session):
    now = _now()
    overview = DashboardOverview(
        stats=_stats(db, now),
        revenue_chart=_revenue_chart(db, now, 9),
        service_breakdown=_service_breakdown(db, now),
        worker_activities=_worker_activities(db, now, 8),
        top_workers=_top_workers(db, 5),
        recent_complaints=_recent_complaints(db, 5),
        recent_orders=_recent_orders(db, 10),
    )
    return success(overview)