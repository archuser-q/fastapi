"""App thợ: thu nhập theo ngày/tuần/tháng, ví, rút tiền, đánh giá & hiệu suất."""

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.controllers.customer_order_controller import order_total
from app.models import (
    Order,
    OrderOffer,
    Payment,
    Review,
    Service,
    User,
    WalletTransaction,
    WorkerBankAccount,
    WorkerEarning,
    WorkerProfile,
    WorkerWithdrawal,
)
from app.schemas.worker_app import (
    EarningItem,
    EarningPoint,
    EarningSummary,
    EarningTotals,
    PerformanceOut,
    ReviewOut,
    ReviewSummary,
    TopupCreate,
    WalletOut,
    WalletTx,
    WithdrawalCreate,
    WithdrawalOut,
)
from app.services import worker_service as ws
from app.services.notification_service import notify
from app.utils.dates import add_months, day_start, month_start, now_vn, percent_change
from app.utils.response import paginated, success

WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
PERIOD_LABEL = {"today": "Hôm nay", "week": "Tuần này", "month": "Tháng này"}
PERFORMANCE_DAYS = 30


# =====================================================================
# Thu nhập
# =====================================================================


def _windows(period: str, now: datetime):
    today = day_start(now)
    if period == "today":
        start, end = today, today + timedelta(days=1)
        prev = (start - timedelta(days=1), start)
    elif period == "week":
        start = today - timedelta(days=today.weekday())  # tuần bắt đầu từ Thứ 2
        end = start + timedelta(days=7)
        prev = (start - timedelta(days=7), start)
    else:
        start = month_start(now)
        end = add_months(start, 1)
        prev = (add_months(start, -1), start)
    # So sánh "cùng kỳ": kỳ trước tính đến đúng thời điểm tương ứng (VD tuần này mới tới Thứ 3 thì so với T2–T3 tuần trước)
    elapsed = min(now, end) - start
    prev = (prev[0], min(prev[1], prev[0] + elapsed))
    return start, end, prev


def _earning_rows(db: Session, worker_id: int, start: datetime, end: datetime):
    return db.execute(
        select(
            WorkerEarning.created_at,
            WorkerEarning.gross_amount,
            WorkerEarning.commission_amount,
            WorkerEarning.net_amount,
            Payment.method,
        )
        .outerjoin(Payment, and_(Payment.order_id == WorkerEarning.order_id, Payment.status == "success"))
        .where(WorkerEarning.worker_id == worker_id, WorkerEarning.created_at >= start, WorkerEarning.created_at < end)
    ).all()


def earnings_summary(db: Session, worker: User, period: str):
    ws.reconcile_worker_finance(db, worker.id)
    now = now_vn()
    start, end, (pstart, pend) = _windows(period, now)
    rows = _earning_rows(db, worker.id, start, end)

    gross = sum(int(r.gross_amount) for r in rows)
    commission = sum(int(r.commission_amount) for r in rows)
    net = sum(int(r.net_amount) for r in rows)
    cash = sum(int(r.gross_amount) for r in rows if r.method == "cash")
    online = sum(int(r.net_amount) for r in rows if r.method and r.method != "cash")
    prev_net = sum(int(r.net_amount) for r in _earning_rows(db, worker.id, pstart, pend))

    # Biểu đồ: Hôm nay -> 7 ngày gần nhất; Tuần -> T2..CN; Tháng -> từng ngày trong tháng
    if period == "today":
        days = [day_start(now) - timedelta(days=i) for i in range(6, -1, -1)]
    elif period == "week":
        days = [start + timedelta(days=i) for i in range(7)]
    else:
        days = [start + timedelta(days=i) for i in range((end - start).days)]
    chart_rows = _earning_rows(db, worker.id, days[0], days[-1] + timedelta(days=1))
    buckets = {d.date(): [0, 0] for d in days}
    for r in chart_rows:
        b = buckets.get(r.created_at.date())
        if b is not None:
            b[0] += int(r.net_amount)
            b[1] += 1
    chart = []
    for d in days:
        if period == "month":
            label = str(d.day)
        elif d.date() == now.date():
            label = "Nay"
        else:
            label = WEEKDAY_SHORT[d.weekday()]
        net_d, cnt = buckets[d.date()]
        chart.append(EarningPoint(key=d.date().isoformat(), label=label, net=net_d, orders=cnt))

    unpaid = db.scalars(
        select(Order).where(
            Order.worker_id == worker.id,
            Order.status == "completed",
            ~select(Payment.id).where(Payment.order_id == Order.id, Payment.status == "success").exists(),
        )
    ).all()
    return success(
        EarningSummary(
            period=period,
            label=PERIOD_LABEL[period],
            start=start,
            end=end,
            totals=EarningTotals(
                orders=len(rows),
                gross=gross,
                commission=commission,
                net=net,
                cash_collected=cash,
                online_received=online,
                avg_net_per_order=round(net / len(rows)) if rows else 0,
            ),
            previous_net=prev_net,
            change_percent=percent_change(net, prev_net),
            chart=chart,
            unpaid_orders=len(unpaid),
            unpaid_amount=sum(order_total(db, o) or 0 for o in unpaid),
        )
    )


def earnings_history(db: Session, worker: User, page: int, page_size: int):
    ws.reconcile_worker_finance(db, worker.id)
    stmt = (
        select(WorkerEarning, Service.name, Payment.method)
        .join(Order, Order.id == WorkerEarning.order_id)
        .join(Service, Service.id == Order.service_id)
        .outerjoin(Payment, and_(Payment.order_id == Order.id, Payment.status == "success"))
        .where(WorkerEarning.worker_id == worker.id)
        .order_by(WorkerEarning.created_at.desc(), WorkerEarning.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        EarningItem(
            order_id=e.order_id,
            service_name=sname,
            gross_amount=int(e.gross_amount),
            commission_amount=int(e.commission_amount),
            net_amount=int(e.net_amount),
            payment_method=method,
            created_at=e.created_at,
        )
        for e, sname, method in rows
    ]
    return paginated(items, total, page, page_size)


# =====================================================================
# Ví & rút tiền
# =====================================================================


def _tx_out(t: WalletTransaction) -> WalletTx:
    return WalletTx(
        id=t.id, type=t.type, amount=int(t.amount), description=t.description, order_id=t.order_id, created_at=t.created_at
    )


def _withdrawal_out(w: WorkerWithdrawal) -> WithdrawalOut:
    return WithdrawalOut(
        id=w.id,
        amount=int(w.amount),
        bank_name=w.bank_name,
        account_number=w.account_number,
        account_holder=w.account_holder,
        status=w.status,
        transaction_code=w.transaction_code,
        note=w.note,
        created_at=w.created_at,
        processed_at=w.processed_at,
    )


def wallet(db: Session, worker: User):
    from app.controllers.worker_profile_controller import _bank

    ws.reconcile_worker_finance(db, worker.id)
    balance = ws.wallet_balance(db, worker.id)
    pending = db.scalar(
        select(func.coalesce(func.sum(WorkerWithdrawal.amount), 0)).where(
            WorkerWithdrawal.worker_id == worker.id, WorkerWithdrawal.status == "pending"
        )
    )
    recent = db.scalars(
        select(WalletTransaction)
        .where(WalletTransaction.worker_id == worker.id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .limit(10)
    ).all()
    return success(
        WalletOut(
            balance=balance,
            available_for_withdrawal=max(0, balance),
            debt_limit=settings.wallet_debt_limit,
            restricted=ws.is_wallet_restricted(balance),
            min_withdrawal=settings.min_withdrawal,
            pending_withdrawal=int(pending),
            bank_account=_bank(db, worker.id),
            recent=[_tx_out(t) for t in recent],
        )
    )


def transactions(db: Session, worker: User, page: int, page_size: int):
    stmt = (
        select(WalletTransaction)
        .where(WalletTransaction.worker_id == worker.id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return paginated([_tx_out(t) for t in rows], total, page, page_size)


def create_withdrawal(db: Session, worker: User, data: WithdrawalCreate):
    # Khóa hồ sơ thợ để 2 yêu cầu rút cùng lúc không vượt số dư
    db.get(WorkerProfile, worker.id, with_for_update=True)
    bank = db.get(WorkerBankAccount, worker.id)
    if not bank:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hãy liên kết tài khoản ngân hàng trước khi rút tiền")
    if data.amount < settings.min_withdrawal:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Số tiền rút tối thiểu {ws.money(settings.min_withdrawal)}")
    balance = ws.wallet_balance(db, worker.id)
    if data.amount > balance:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Số dư khả dụng chỉ còn {ws.money(max(0, balance))}")

    now = now_vn()
    w = WorkerWithdrawal(
        worker_id=worker.id,
        amount=data.amount,
        bank_name=bank.bank_name,
        account_number=bank.account_number,
        account_holder=bank.account_holder,
        created_at=now,
    )
    db.add(w)
    db.flush()
    tail = bank.account_number[-4:]
    db.add(
        WalletTransaction(
            worker_id=worker.id,
            type="withdrawal",
            amount=-data.amount,
            withdrawal_id=w.id,
            description=f"Rút tiền về {bank.bank_name} ****{tail}",
            created_at=now,
        )
    )
    if settings.withdrawal_auto_approve:  # môi trường demo: duyệt ngay
        w.status = "completed"
        w.processed_at = now
        w.transaction_code = f"SANDBOX-WD-{uuid.uuid4().hex[:10].upper()}"
        notify(db, worker.id, "Rút tiền thành công", f"{ws.money(data.amount)} đã chuyển về {bank.bank_name} ****{tail}", "withdrawal", w.id)
    db.commit()
    db.refresh(w)
    msg = "Rút tiền thành công" if w.status == "completed" else "Đã gửi yêu cầu rút tiền, chờ duyệt"
    return success(_withdrawal_out(w), msg)


def list_withdrawals(db: Session, worker: User, page: int, page_size: int):
    stmt = (
        select(WorkerWithdrawal)
        .where(WorkerWithdrawal.worker_id == worker.id)
        .order_by(WorkerWithdrawal.created_at.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return paginated([_withdrawal_out(w) for w in rows], total, page, page_size)


def topup(db: Session, worker: User, data: TopupCreate):
    """Nạp tiền vào ví để bù hoa hồng đơn tiền mặt — giả lập cổng thanh toán (chỉ khi DEBUG=true)."""
    if not settings.debug:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    db.add(
        WalletTransaction(
            worker_id=worker.id,
            type="topup",
            amount=data.amount,
            description=f"Nạp tiền vào ví qua {'MoMo' if data.method == 'momo' else 'VNPay'} (sandbox)",
            created_at=now_vn(),
        )
    )
    db.commit()
    return wallet(db, worker)


# =====================================================================
# Đánh giá & hiệu suất
# =====================================================================


def reviews(db: Session, worker: User, rating: int | None, page: int, page_size: int):
    dist_rows = db.execute(
        select(Review.rating, func.count())
        .where(Review.worker_id == worker.id, Review.is_hidden.is_(False))
        .group_by(Review.rating)
    ).all()
    dist = {i: 0 for i in range(1, 6)}
    for r, n in dist_rows:
        dist[int(r)] = n
    count = sum(dist.values())
    avg = round(sum(k * v for k, v in dist.items()) / count, 2) if count else None

    stmt = (
        select(Review, User.full_name, Service.name)
        .join(User, User.id == Review.customer_id)
        .join(Order, Order.id == Review.order_id)
        .join(Service, Service.id == Order.service_id)
        .where(Review.worker_id == worker.id, Review.is_hidden.is_(False))
    )
    if rating:
        stmt = stmt.where(Review.rating == rating)
    stmt = stmt.order_by(Review.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    data = paginated(
        [
            ReviewOut(
                id=r.id,
                order_id=r.order_id,
                rating=r.rating,
                comment=r.comment,
                customer_name=ws.given_name(cname),
                service_name=sname,
                created_at=r.created_at,
            )
            for r, cname, sname in rows
        ],
        total,
        page,
        page_size,
    )
    data["data"]["summary"] = ReviewSummary(rating_avg=avg, review_count=count, distribution=dist)
    return data


def performance(db: Session, worker: User):
    from app.controllers.worker_profile_controller import offer_counts_for, rating_avg

    ws.reconcile_worker_finance(db, worker.id)
    now = now_vn()
    since = now - timedelta(days=PERFORMANCE_DAYS)
    counts = offer_counts_for(db, worker.id, since)
    accepted = counts.get("accepted", 0) + counts.get("cancelled", 0)
    rejected = counts.get("rejected", 0)
    expired = counts.get("expired", 0)
    answered = accepted + rejected + expired
    completed = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.worker_id == worker.id, Order.status == "completed", Order.completed_at >= since)
    )
    cancelled = db.scalar(
        select(func.count())
        .select_from(OrderOffer)
        .where(OrderOffer.worker_id == worker.id, OrderOffer.status == "cancelled", OrderOffer.responded_at >= since)
    )
    profile = db.get(WorkerProfile, worker.id)
    total_net = db.scalar(
        select(func.coalesce(func.sum(WorkerEarning.net_amount), 0)).where(WorkerEarning.worker_id == worker.id)
    )
    return success(
        PerformanceOut(
            period_days=PERFORMANCE_DAYS,
            offers_received=sum(counts.values()),
            offers_accepted=accepted,
            offers_rejected=rejected,
            offers_expired=expired,
            acceptance_rate=round(accepted / answered, 4) if answered else None,
            jobs_completed=completed,
            jobs_cancelled_by_worker=cancelled,
            completion_rate=round(completed / (completed + cancelled), 4) if completed + cancelled else None,
            rating_avg=rating_avg(db, worker.id),
            review_count=profile.review_count if profile else 0,
            trust_score=float(profile.trust_score) if profile else 0.0,
            total_completed=profile.completed_orders if profile else 0,
            total_net=int(total_net),
        )
    )
