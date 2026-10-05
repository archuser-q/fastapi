from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import (
    Complaint,
    MatchingConfig,
    Order,
    OrderOffer,
    Payment,
    Review,
    Service,
    ServiceCategory,
    User,
    WorkerDocument,
    WorkerEarning,
    WorkerProfile,
)
from app.schemas.dashboard import (
    CatalogSummary,
    ComplaintsSummary,
    DashboardKpis,
    HourlyPoint,
    KpiValue,
    MatchingConfigBrief,
    MethodShare,
    OrdersByHour,
    OrdersSummary,
    PaymentsSummary,
    PendingTask,
    PendingTasks,
    QuickView,
    RatingBucket,
    ReviewsSummary,
    StatusCount,
    SystemSummary,
    UsersSummary,
    WorkersSummary,
)
from app.utils.dates import day_start, month_start, now_vn, percent_change, period_windows
from app.utils.response import success

ORDER_STATUS_LABELS = {
    "pending": "Chờ ghép thợ",
    "matched": "Đã ghép thợ",
    "accepted": "Thợ đã nhận",
    "on_the_way": "Đang đến",
    "arrived": "Đã đến nơi",
    "in_progress": "Đang thực hiện",
    "completed": "Hoàn thành",
    "cancelled": "Đã hủy",
}
ACTIVE_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress")
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}


def _int(v) -> int:
    return int(v or 0)


def _round(v, n: int = 2) -> float | None:
    return round(float(v), n) if v is not None else None


def _ratio(part, whole) -> float | None:
    return round(part / whole * 100, 1) if whole else None


# ---------- System summary ----------


def _users_summary(db: Session, m_start: datetime) -> UsersSummary:
    row = db.execute(
        select(
            func.count().filter(User.role == "customer"),
            func.count().filter(User.role == "worker"),
            func.count().filter(User.role == "admin"),
            func.count().filter(User.status == "blocked"),
            func.count().filter(User.role == "customer", User.created_at >= m_start),
            func.count().filter(User.role == "worker", User.created_at >= m_start),
        ).select_from(User)
    ).one()
    return UsersSummary(
        customers=row[0],
        workers=row[1],
        admins=row[2],
        blocked=row[3],
        new_customers_month=row[4],
        new_workers_month=row[5],
    )


def _workers_summary(db: Session) -> WorkersSummary:
    approved_active = and_(WorkerProfile.verification_status == "approved", User.status == "active")
    row = db.execute(
        select(
            func.count().filter(WorkerProfile.verification_status == "pending"),
            func.count().filter(WorkerProfile.verification_status == "approved"),
            func.count().filter(WorkerProfile.verification_status == "rejected"),
            func.count().filter(approved_active, WorkerProfile.availability == "online"),
            func.count().filter(approved_active, WorkerProfile.availability == "busy"),
            func.count().filter(approved_active, WorkerProfile.availability == "offline"),
        )
        .select_from(WorkerProfile)
        .join(User, User.id == WorkerProfile.user_id)
    ).one()
    pending_docs = db.scalar(
        select(func.count(WorkerDocument.id)).where(WorkerDocument.status == "pending")
    )
    return WorkersSummary(
        pending=row[0],
        approved=row[1],
        rejected=row[2],
        online=row[3],
        busy=row[4],
        offline=row[5],
        pending_documents=pending_docs,
    )


def _orders_summary(db: Session, today: datetime) -> OrdersSummary:
    counts = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    completed_today, cancelled_today = db.execute(
        select(
            func.count().filter(Order.status == "completed", Order.completed_at >= today),
            func.count().filter(Order.status == "cancelled", Order.created_at >= today),
        ).select_from(Order)
    ).one()
    return OrdersSummary(
        total=sum(counts.values()),
        waiting=counts.get("pending", 0),
        active=sum(counts.get(s, 0) for s in ACTIVE_STATUSES),
        completed_today=completed_today,
        cancelled_today=cancelled_today,
        by_status=[
            StatusCount(status=s, label=label, count=counts.get(s, 0))
            for s, label in ORDER_STATUS_LABELS.items()
        ],
    )


def _complaints_summary(db: Session) -> ComplaintsSummary:
    counts = dict(
        db.execute(select(Complaint.status, func.count()).group_by(Complaint.status)).all()
    )
    avg_seconds = db.scalar(
        select(
            func.avg(func.extract("epoch", Complaint.resolved_at - Complaint.created_at))
        ).where(Complaint.resolved_at.is_not(None))
    )
    return ComplaintsSummary(
        open=counts.get("open", 0),
        processing=counts.get("processing", 0),
        resolved=counts.get("resolved", 0),
        rejected=counts.get("rejected", 0),
        avg_resolution_hours=_round(avg_seconds / 3600, 1) if avg_seconds is not None else None,
    )


def _reviews_summary(db: Session) -> ReviewsSummary:
    total, avg, flagged = db.execute(
        select(
            func.count(Review.id),
            func.avg(Review.rating),
            func.count().filter(Review.is_flagged.is_(True)),
        )
    ).one()
    stars = dict(db.execute(select(Review.rating, func.count()).group_by(Review.rating)).all())
    distribution = [
        RatingBucket(star=s, count=stars.get(s, 0), percent=_ratio(stars.get(s, 0), total) or 0)
        for s in range(5, 0, -1)
    ]
    return ReviewsSummary(total=total, average=_round(avg), flagged=flagged, distribution=distribution)


def _payments_summary(db: Session, today: datetime, m_start: datetime) -> PaymentsSummary:
    paid = and_(Payment.status == "success", Payment.paid_at.is_not(None))
    row = db.execute(
        select(
            func.coalesce(func.sum(Payment.amount).filter(paid, Payment.paid_at >= today), 0),
            func.coalesce(func.sum(Payment.amount).filter(paid, Payment.paid_at >= m_start), 0),
            func.count().filter(Payment.status == "pending"),
            func.count().filter(Payment.status == "failed", Payment.created_at >= m_start),
        ).select_from(Payment)
    ).one()
    methods = db.execute(
        select(Payment.method, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(paid, Payment.paid_at >= m_start)
        .group_by(Payment.method)
        .order_by(func.sum(Payment.amount).desc())
    ).all()
    commission = db.scalar(
        select(func.coalesce(func.sum(WorkerEarning.commission_amount), 0)).where(
            WorkerEarning.created_at >= m_start
        )
    )
    return PaymentsSummary(
        success_today_amount=_int(row[0]),
        success_month_amount=_int(row[1]),
        commission_month_amount=_int(commission),
        pending=row[2],
        failed_month=row[3],
        by_method_month=[MethodShare(method=m[0], count=m[1], amount=_int(m[2])) for m in methods],
    )


def _catalog_summary(db: Session) -> CatalogSummary:
    categories = db.scalar(
        select(func.count(ServiceCategory.id)).where(ServiceCategory.is_active.is_(True))
    )
    active, inactive = db.execute(
        select(
            func.count().filter(Service.is_active.is_(True)),
            func.count().filter(Service.is_active.is_(False)),
        ).select_from(Service)
    ).one()
    return CatalogSummary(
        categories_active=categories, services_active=active, services_inactive=inactive
    )


def _active_matching(db: Session) -> MatchingConfigBrief | None:
    cfg = db.scalars(
        select(MatchingConfig)
        .where(MatchingConfig.is_active.is_(True))
        .order_by(MatchingConfig.updated_at.desc())
        .limit(1)
    ).first()
    if not cfg:
        return None
    return MatchingConfigBrief(
        id=cfg.id,
        name=cfg.name,
        mode=cfg.mode,
        weight_distance=float(cfg.weight_distance),
        weight_trust=float(cfg.weight_trust),
        weight_price=float(cfg.weight_price),
        weight_workload=float(cfg.weight_workload),
        batch_window_seconds=cfg.batch_window_seconds,
        updated_at=cfg.updated_at,
    )


def _system_summary(db: Session, now: datetime) -> SystemSummary:
    today = day_start(now)
    m_start = month_start(now)
    return SystemSummary(
        generated_at=now,
        users=_users_summary(db, m_start),
        workers=_workers_summary(db),
        orders=_orders_summary(db, today),
        complaints=_complaints_summary(db),
        reviews=_reviews_summary(db),
        payments=_payments_summary(db, today, m_start),
        catalog=_catalog_summary(db),
        matching=_active_matching(db),
    )


# ---------- Pending tasks ----------


def _task(db, now, key, title, link, base, sla_minutes, time_col, select_from, *conditions):
    cutoff = now - timedelta(minutes=sla_minutes)
    stmt = select(func.count(), func.count().filter(time_col < cutoff), func.min(time_col))
    for i, target in enumerate(select_from):
        stmt = stmt.select_from(target) if i == 0 else stmt.join(*target)
    count, overdue, oldest = db.execute(stmt.where(*conditions)).one()

    if count == 0:
        severity = "none"
    elif overdue > 0:
        severity = "high"
    else:
        severity = base

    return PendingTask(
        key=key,
        title=title,
        count=count,
        overdue=overdue,
        sla_minutes=sla_minutes,
        oldest_at=oldest,
        severity=severity,
        link=link,
    )


def _pending_tasks(db: Session, now: datetime) -> PendingTasks:
    items = [
        _task(
            db, now, "worker_verification", "Thợ chờ xác minh hồ sơ",
            "/workers?verification_status=pending", "medium", 48 * 60,
            WorkerProfile.created_at,
            [WorkerProfile, (User, User.id == WorkerProfile.user_id)],
            WorkerProfile.verification_status == "pending", User.status != "blocked",
        ),
        _task(
            db, now, "worker_documents", "Giấy tờ thợ chờ duyệt",
            "/workers?verification_status=pending", "low", 48 * 60,
            WorkerDocument.uploaded_at, [WorkerDocument],
            WorkerDocument.status == "pending",
        ),
        _task(
            db, now, "complaints_open", "Khiếu nại mới chưa tiếp nhận",
            "/complaints?status=open", "medium", 24 * 60,
            Complaint.created_at, [Complaint],
            Complaint.status == "open",
        ),
        _task(
            db, now, "complaints_processing", "Khiếu nại đang xử lý",
            "/complaints?status=processing", "low", 72 * 60,
            Complaint.created_at, [Complaint],
            Complaint.status == "processing",
        ),
        _task(
            db, now, "unmatched_orders", "Đơn chưa ghép được thợ",
            "/orders?status=pending", "medium", 15,
            func.coalesce(Order.scheduled_at, Order.created_at), [Order],
            Order.status == "pending",
        ),
        _task(
            db, now, "flagged_reviews", "Đánh giá bị gắn cờ",
            "/reviews?flagged=true", "low", 48 * 60,
            Review.created_at, [Review],
            Review.is_flagged.is_(True),
        ),
        _task(
            db, now, "pending_payments", "Thanh toán đang treo",
            "/payments?status=pending", "low", 24 * 60,
            Payment.created_at, [Payment],
            Payment.status == "pending",
        ),
    ]
    items.sort(key=lambda t: (SEVERITY_RANK[t.severity], -t.overdue, -t.count))
    return PendingTasks(
        total=sum(t.count for t in items),
        total_overdue=sum(t.overdue for t in items),
        items=items,
    )


# ---------- KPIs ----------


def _window_metrics(db: Session, start: datetime, end: datetime) -> dict:
    created_in = and_(Order.created_at >= start, Order.created_at < end)
    completed_in = and_(
        Order.status == "completed", Order.completed_at >= start, Order.completed_at < end
    )
    accepted_in = and_(Order.accepted_at >= start, Order.accepted_at < end)

    o = db.execute(
        select(
            func.count().filter(created_in),
            func.count().filter(created_in, Order.status == "completed"),
            func.count().filter(created_in, Order.status == "cancelled"),
            func.count().filter(completed_in),
            func.coalesce(func.sum(Order.final_price).filter(completed_in), 0),
            func.avg(func.extract("epoch", Order.accepted_at - Order.created_at)).filter(
                accepted_in
            ),
            func.avg(func.extract("epoch", Order.completed_at - Order.accepted_at)).filter(
                completed_in, Order.accepted_at.is_not(None)
            ),
        ).select_from(Order)
    ).one()
    created, cohort_completed, cohort_cancelled, completed, revenue, match_s, service_s = o
    closed = cohort_completed + cohort_cancelled

    offers_answered, offers_accepted = db.execute(
        select(
            func.count().filter(OrderOffer.status != "sent"),
            func.count().filter(OrderOffer.status == "accepted"),
        ).where(OrderOffer.sent_at >= start, OrderOffer.sent_at < end)
    ).one()

    commission = db.scalar(
        select(func.coalesce(func.sum(WorkerEarning.commission_amount), 0)).where(
            WorkerEarning.created_at >= start, WorkerEarning.created_at < end
        )
    )

    new_customers, new_workers = db.execute(
        select(
            func.count().filter(User.role == "customer"),
            func.count().filter(User.role == "worker"),
        ).where(User.created_at >= start, User.created_at < end)
    ).one()

    avg_rating = db.scalar(
        select(func.avg(Review.rating)).where(Review.created_at >= start, Review.created_at < end)
    )

    revenue = _int(revenue)
    return {
        "orders_created": created,
        "orders_completed": completed,
        "completion_rate": _ratio(cohort_completed, closed),
        "cancellation_rate": _ratio(cohort_cancelled, closed),
        "avg_match_minutes": _round(match_s / 60, 1) if match_s is not None else None,
        "avg_service_minutes": _round(service_s / 60, 1) if service_s is not None else None,
        "offer_acceptance_rate": _ratio(offers_accepted, offers_answered),
        "revenue": revenue,
        "commission": _int(commission),
        "avg_order_value": round(revenue / completed) if completed else None,
        "new_customers": new_customers,
        "new_workers": new_workers,
        "avg_rating": _round(avg_rating),
    }


def _kpi(cur, prev) -> KpiValue:
    change = round(cur - prev, 2) if cur is not None and prev is not None else None
    return KpiValue(value=cur, previous=prev, change=change, change_percent=percent_change(cur, prev))


def _kpis(db: Session, now: datetime, period: str) -> DashboardKpis:
    (start, end), (p_start, p_end) = period_windows(now, period)
    cur = _window_metrics(db, start, end)
    prev = _window_metrics(db, p_start, p_end)
    return DashboardKpis(
        period=period,
        start=start,
        end=end,
        **{k: _kpi(cur[k], prev[k]) for k in cur},
    )


# ---------- Orders by hour ----------


def _orders_by_hour(db: Session, now: datetime, target: date | None) -> OrdersByHour:
    day = day_start(datetime.combine(target, datetime.min.time())) if target else day_start(now)
    prev_day = day - timedelta(days=1)

    hour = func.extract("hour", Order.created_at)
    is_target = case((Order.created_at >= day, 1), else_=0)
    rows = db.execute(
        select(hour, is_target, func.count())
        .where(Order.created_at >= prev_day, Order.created_at < day + timedelta(days=1))
        .group_by(hour, is_target)
    ).all()

    cur = {int(h): c for h, t, c in rows if t == 1}
    prev = {int(h): c for h, t, c in rows if t == 0}
    points = [
        HourlyPoint(hour=h, label=f"{h:02d}h", orders=cur.get(h, 0), previous_orders=prev.get(h, 0))
        for h in range(24)
    ]
    total = sum(cur.values())
    return OrdersByHour(
        date=day.strftime("%Y-%m-%d"),
        compare_date=prev_day.strftime("%Y-%m-%d"),
        total=total,
        previous_total=sum(prev.values()),
        peak_hour=max(cur, key=cur.get) if total else None,
        points=points,
    )


# ---------- Handlers ----------


def get_system_summary(db: Session):
    return success(_system_summary(db, now_vn()))


def get_pending_tasks(db: Session):
    return success(_pending_tasks(db, now_vn()))


def get_kpis(db: Session, period: str):
    return success(_kpis(db, now_vn(), period))


def get_orders_by_hour(db: Session, target: date | None):
    return success(_orders_by_hour(db, now_vn(), target))


def get_quick_view(db: Session, period: str):
    now = now_vn()
    return success(
        QuickView(
            summary=_system_summary(db, now),
            pending_tasks=_pending_tasks(db, now),
            kpis=_kpis(db, now, period),
        )
    )
