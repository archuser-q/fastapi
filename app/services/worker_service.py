"""Nghiệp vụ dùng chung về thợ: trạng thái bận/rảnh, lịch hẹn, ví & thu nhập, hạng thợ."""

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Order,
    OrderOffer,
    Payment,
    WalletTransaction,
    WorkerEarning,
    WorkerProfile,
)
from app.utils.dates import now_vn

# Đơn thợ đang giữ (đã nhận, chưa xong)
OPEN_JOB_STATUSES = ("accepted", "on_the_way", "arrived", "in_progress")
# Đơn thợ đang thực hiện thật sự (đã xuất phát)
INFLIGHT_STATUSES = ("on_the_way", "arrived", "in_progress")
# Đơn hẹn trước: trong vòng 60 phút trước giờ hẹn thợ được tính là bận (chuẩn bị đi) và mới được bắt đầu di chuyển
BUSY_BEFORE_SCHEDULE_MINUTES = 60
PAYMENT_LABEL = {"cash": "tiền mặt", "momo": "MoMo", "vnpay": "VNPay"}


def order_code(order_id: int) -> str:
    return f"ĐH-{order_id}"


def money(n: int | float) -> str:
    return f"{int(n):,}đ".replace(",", ".")


def given_name(full_name: str | None) -> str:
    """Tên gọi ngắn để hiện cho thợ trước khi nhận đơn (không lộ họ tên đầy đủ)."""
    if not full_name:
        return "Khách hàng"
    return full_name.strip().split()[-1]


# ---------- Trạng thái làm việc ----------


def refresh_availability(db: Session, worker_id: int | None) -> None:
    """Tính lại online/busy sau khi nhận/hoàn thành/hủy đơn. Thợ đang tắt nhận đơn thì giữ offline."""
    if worker_id is None:
        return
    profile = db.get(WorkerProfile, worker_id)
    if not profile or profile.availability == "offline":
        return
    db.flush()  # session tắt autoflush: đẩy thay đổi trạng thái đơn trước khi đếm
    soon = now_vn() + timedelta(minutes=BUSY_BEFORE_SCHEDULE_MINUTES)
    busy = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.worker_id == worker_id,
            or_(
                Order.status.in_(INFLIGHT_STATUSES),
                and_(
                    Order.status == "accepted",
                    or_(Order.scheduled_at.is_(None), Order.scheduled_at <= soon),
                ),
            ),
        )
    )
    profile.availability = "busy" if busy else "online"


def workers_with_live_offers(db: Session, worker_ids: list[int] | None = None) -> set[int]:
    now = now_vn()
    stmt = select(OrderOffer.worker_id).where(OrderOffer.status == "sent", OrderOffer.expires_at > now)
    if worker_ids is not None:
        if not worker_ids:
            return set()
        stmt = stmt.where(OrderOffer.worker_id.in_(worker_ids))
    return set(db.scalars(stmt).all())


def conflicting_workers(db: Session, worker_ids: list[int], when: datetime, exclude_order_id: int | None = None) -> set[int]:
    """Thợ đã có việc khác trong khoảng ± schedule_conflict_minutes quanh thời điểm `when`."""
    if not worker_ids:
        return set()
    window = timedelta(minutes=settings.schedule_conflict_minutes)
    expected = func.coalesce(Order.scheduled_at, Order.accepted_at, Order.created_at)
    stmt = select(Order.worker_id).where(
        Order.worker_id.in_(worker_ids),
        Order.status.in_(OPEN_JOB_STATUSES),
        expected.between(when - window, when + window),
    )
    if exclude_order_id:
        stmt = stmt.where(Order.id != exclude_order_id)
    return set(db.scalars(stmt).all())


def has_inflight_instant_job(db: Session, worker_id: int, exclude_order_id: int | None = None) -> bool:
    stmt = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.worker_id == worker_id,
            or_(
                Order.status.in_(INFLIGHT_STATUSES),
                and_(Order.status == "accepted", Order.scheduled_at.is_(None)),
            ),
        )
    )
    if exclude_order_id:
        stmt = stmt.where(Order.id != exclude_order_id)
    return bool(db.scalar(stmt))


# ---------- Ví ----------


def wallet_balances(db: Session, worker_ids: list[int]) -> dict[int, int]:
    if not worker_ids:
        return {}
    rows = db.execute(
        select(WalletTransaction.worker_id, func.coalesce(func.sum(WalletTransaction.amount), 0))
        .where(WalletTransaction.worker_id.in_(worker_ids))
        .group_by(WalletTransaction.worker_id)
    ).all()
    return {wid: int(total) for wid, total in rows}


def wallet_balance(db: Session, worker_id: int) -> int:
    return wallet_balances(db, [worker_id]).get(worker_id, 0)


def is_wallet_restricted(balance: int) -> bool:
    return balance < -settings.wallet_debt_limit


def commission_of(gross: int) -> int:
    return int(round(gross * settings.commission_rate))


def record_paid_order(db: Session, order: Order, payment: Payment) -> None:
    """Gọi khi 1 thanh toán của đơn thành công: ghi thu nhập của thợ + bút toán ví.

    - Khách trả online (MoMo/VNPay): nền tảng giữ tiền -> cộng vào ví thợ phần thực nhận.
    - Khách trả tiền mặt: thợ đã cầm đủ tiền -> trừ phần hoa hồng khỏi ví thợ.
    (Giống mô hình ví tín dụng / ví tiền mặt của các app gọi xe.)
    Gọi lặp lại không sao (idempotent).
    """
    if order.worker_id is None:
        return
    earning = db.scalar(select(WorkerEarning).where(WorkerEarning.order_id == order.id))
    if earning is None:
        gross = int(payment.amount)
        commission = commission_of(gross)
        earning = WorkerEarning(
            worker_id=order.worker_id,
            order_id=order.id,
            gross_amount=gross,
            commission_amount=commission,
            net_amount=gross - commission,
            created_at=payment.paid_at or now_vn(),
        )
        db.add(earning)
        db.flush()
    _ensure_wallet_entry(db, order, earning, payment.method)


def _ensure_wallet_entry(db: Session, order: Order, earning: WorkerEarning, method: str) -> None:
    tx_type = "commission" if method == "cash" else "earning"
    exists = db.scalar(
        select(WalletTransaction.id).where(WalletTransaction.order_id == order.id, WalletTransaction.type == tx_type)
    )
    if exists:
        return
    rate = round(settings.commission_rate * 100)
    if method == "cash":
        amount = -int(earning.commission_amount)
        desc = f"Trừ hoa hồng {rate}% đơn {order_code(order.id)} (khách trả tiền mặt)"
    else:
        amount = int(earning.net_amount)
        desc = f"Thu nhập đơn {order_code(order.id)} (khách trả qua {PAYMENT_LABEL.get(method, method)})"
    db.add(
        WalletTransaction(
            worker_id=earning.worker_id,
            type=tx_type,
            amount=amount,
            order_id=order.id,
            description=desc,
            created_at=earning.created_at,
        )
    )


def reconcile_worker_finance(db: Session, worker_id: int) -> None:
    """Bù các bút toán còn thiếu (đơn đã thanh toán nhưng chưa ghi thu nhập/ví — VD dữ liệu seed,
    hoặc thanh toán đi qua đường khác). Chạy trước khi trả số liệu thu nhập/ví."""
    rows = db.execute(
        select(Order, Payment)
        .join(Payment, Payment.order_id == Order.id)
        .outerjoin(WorkerEarning, WorkerEarning.order_id == Order.id)
        .outerjoin(
            WalletTransaction,
            and_(WalletTransaction.order_id == Order.id, WalletTransaction.type.in_(("earning", "commission"))),
        )
        .where(
            Order.worker_id == worker_id,
            Order.status == "completed",
            Payment.status == "success",
            or_(WorkerEarning.id.is_(None), WalletTransaction.id.is_(None)),
        )
    ).all()
    if not rows:
        return
    for order, payment in rows:
        record_paid_order(db, order, payment)
    db.commit()


# ---------- Hạng thợ (theo kinh nghiệm thực tế trên nền tảng) ----------

LEVELS = (
    ("dong", "Thợ Đồng", 0, 0.0),
    ("bac", "Thợ Bạc", 30, 4.5),
    ("vang", "Thợ Vàng", 100, 4.7),
    ("kim_cuong", "Thợ Kim cương", 300, 4.85),
)


def worker_level(completed: int, rating: float | None) -> dict:
    """Hạng = mốc số đơn hoàn thành + điểm đánh giá tối thiểu. Chỉ để hiển thị (không ảnh hưởng thuật toán ghép)."""
    r = 5.0 if rating is None else rating
    idx = 0
    for i, (_, _, jobs, min_rating) in enumerate(LEVELS):
        if completed >= jobs and r >= min_rating:
            idx = i
    key, name, jobs, _ = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    progress = 1.0 if nxt is None else max(0.0, min(1.0, (completed - jobs) / max(1, nxt[2] - jobs)))
    return {
        "key": key,
        "name": name,
        "completed": completed,
        "next_name": nxt[1] if nxt else None,
        "next_jobs": nxt[2] if nxt else None,
        "next_rating": nxt[3] if nxt else None,
        "progress": round(progress, 3),
    }


# ---------- Bản đồ nhu cầu quanh thợ ----------




