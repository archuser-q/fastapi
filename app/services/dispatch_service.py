"""Bộ điều phối đơn — đưa thuật toán ghép cặp vào vận hành thật (Thành viên B).

Vòng đời 1 đơn đang tìm thợ:

    tạo đơn ──> order_dispatches (hàng đợi) ──> gửi offer ──> thợ nhận ──> accepted
                    ^                              │
                    └── hết hạn / từ chối ─────────┘  (đơn quay lại hàng đợi, KHÔNG gửi lại cho thợ cũ)
    quá hạn chờ (deadline) mà chưa ai nhận ──> hệ thống hủy đơn, báo khách

Hai chế độ (admin chọn ở cấu hình matching đang áp dụng):

* instant – Weighted Scoring + Greedy theo đợt (wave):
      mỗi đợt xếp hạng ứng viên hợp lệ, gửi offer cho top-k (k = max_offers) cùng lúc, ai nhận trước
      được đơn; hết offer_timeout_seconds mà không ai nhận -> đợt tiếp theo cho các thợ xếp sau.
* batch – Batch Optimal Assignment:
      cứ batch_window_seconds gom TẤT CẢ đơn đang chờ + thợ đang rảnh thành ma trận điểm,
      giải bài toán gán 2 phía bằng Hungarian (app/matching/hungarian.py) để tối đa tổng điểm
      toàn cục, mỗi đơn gửi offer cho đúng thợ được gán.
* auto – Hybrid tự thích ứng (khuyến nghị): mỗi nhịp điều phối (vài giây) gom các đơn đang chờ,
      chia thành NHÓM TRANH CHẤP (các đơn có chung ít nhất 1 thợ ứng viên, nối bắc cầu):
        - đơn đứng một mình (không tranh thợ với ai)  -> gửi ngay kiểu tức thời cho top-k
        - nhóm >= 2 đơn tranh cùng thợ               -> Hungarian trên nhóm đó, mỗi đơn 1 offer
      Vắng khách thì gần như luôn là tức thời (nhanh, không phải chờ cửa sổ lô); cao điểm thì tự
      chuyển sang tối ưu toàn cục — đúng kết luận của thực nghiệm (docs/thuc-nghiem-ghep-cap).

Ràng buộc cứng (lọc trước khi chấm điểm):
  đã duyệt hồ sơ, tài khoản hoạt động, có kỹ năng dịch vụ, trong bán kính tìm & bán kính nhận việc,
  vị trí còn mới, đang bật nhận đơn (đơn đặt ngay: phải rảnh), không đang giữ offer khác,
  chưa từng được mời đơn này, ví không âm quá hạn mức, không trùng lịch hẹn khác.

Mọi quyết định điều phối chạy tuần tự nhờ khóa advisory của PostgreSQL, nên 2 đơn không thể
cùng "giành" 1 thợ, và chạy được an toàn khi API có nhiều tiến trình.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import exists, select, text, update
from sqlalchemy.orm import Session

from app.config import settings
from app.matching.grouping import competition_groups
from app.matching.hungarian import hungarian_max
from app.models import (
    Notification,
    Order,
    OrderDispatch,
    OrderOffer,
    OrderStatusHistory,
    Service,
    User,
    WorkerProfile,
)
from app.schemas.geo import NearbyWorker
from app.services import worker_service as ws
from app.services.matching_service import (
    ActiveConfig,
    ScoredWorker,
    find_candidates,
    load_active_config,
    score_candidates,
)
from app.services.notification_service import notify
from app.utils.dates import now_vn

log = logging.getLogger("thonhanh.dispatch")

DISPATCH_LOCK_KEY = 815_001


def _lock(db: Session) -> None:
    """Khóa advisory theo giao dịch: các thao tác điều phối chạy lần lượt."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": DISPATCH_LOCK_KEY})


def _history(db: Session, order: Order, new_status: str, user_id: int | None) -> None:
    db.add(OrderStatusHistory(order_id=order.id, status=new_status, changed_by=user_id, created_at=now_vn()))


def _live_offer_exists(db: Session, order_id: int):
    now = now_vn()
    return db.scalar(
        select(
            exists().where(
                OrderOffer.order_id == order_id,
                OrderOffer.status == "sent",
                OrderOffer.expires_at > now,
            )
        )
    )


def _deadline(order: Order):
    now = now_vn()
    if order.scheduled_at and order.scheduled_at > now:
        return max(
            order.scheduled_at - timedelta(minutes=settings.scheduled_cancel_before_minutes),
            now + timedelta(minutes=5),
        )
    return now + timedelta(minutes=settings.dispatch_max_wait_minutes)


# ---------- Bắt đầu điều phối ----------


def start_dispatch(db: Session, order_id: int) -> None:
    """Gọi ngay sau khi khách tạo đơn (đơn đã commit)."""
    order = db.get(Order, order_id)
    if not order or order.status != "pending":
        return
    cfg = load_active_config(db)
    # Chế độ do hệ thống (admin) quyết định, không do khách chọn. Với "auto", đơn ghi chế độ thực tế khi gửi offer.
    order.matching_mode = _order_mode(cfg.mode)
    if db.get(OrderDispatch, order.id) is None:
        db.add(OrderDispatch(order_id=order.id, mode=cfg.mode, next_attempt_at=now_vn(), deadline_at=_deadline(order)))
    db.commit()
    if cfg.mode == "instant":
        run_instant_wave(db, order.id, cfg)
    # auto: nhịp điều phối kế tiếp (<= vài giây) xử lý, để các đơn đến gần nhau được xét chung


def _order_mode(cfg_mode: str) -> str:
    """Giá trị ghi vào orders.matching_mode (chỉ 'instant' | 'batch'); auto tạm ghi 'instant' tới khi gửi offer."""
    return "instant" if cfg_mode == "auto" else cfg_mode


def _adopt_orphans(db: Session) -> None:
    """Đơn pending chưa có dòng điều phối (tạo trước khi có tính năng / tạo bằng script) -> nhận vào hàng đợi."""
    now = now_vn()
    recent = now - timedelta(minutes=settings.dispatch_max_wait_minutes)
    orphans = db.scalars(
        select(Order).where(
            Order.status == "pending",
            Order.worker_id.is_(None),
            ~exists().where(OrderDispatch.order_id == Order.id),
            (Order.created_at >= recent) | (Order.scheduled_at > now),
        )
    ).all()
    if not orphans:
        return
    cfg = load_active_config(db)
    for o in orphans:
        o.matching_mode = o.matching_mode or _order_mode(cfg.mode)
        db.add(OrderDispatch(order_id=o.id, mode=cfg.mode, next_attempt_at=now, deadline_at=_deadline(o)))
    db.commit()


# ---------- Lọc ứng viên hợp lệ ----------


def _offered_workers(db: Session, order_id: int) -> set[int]:
    return set(db.scalars(select(OrderOffer.worker_id).where(OrderOffer.order_id == order_id)).all())


def filter_eligible(
    db: Session,
    order: Order,
    candidates: list[NearbyWorker],
    blocked: set[int] | None = None,
) -> list[NearbyWorker]:
    """Bước 2: áp ràng buộc cứng của nghiệp vụ lên danh sách ứng viên đã lọc theo không gian."""
    if not candidates:
        return []
    blocked = set(blocked or ()) | _offered_workers(db, order.id)
    ids = [c.worker_id for c in candidates if c.worker_id not in blocked]
    if not ids:
        return []
    blocked |= ws.workers_with_live_offers(db, ids)

    balances = ws.wallet_balances(db, ids)
    blocked |= {wid for wid, bal in balances.items() if ws.is_wallet_restricted(bal)}

    now = now_vn()
    when = order.scheduled_at if order.scheduled_at and order.scheduled_at > now else now
    remaining = [wid for wid in ids if wid not in blocked]
    # Đơn hẹn trước: lời mời ghi rõ giờ hẹn, thợ tự quyết nhận hay không; hệ thống chỉ chặn thợ đã có lịch trùng giờ
    blocked |= ws.conflicting_workers(db, remaining, when, exclude_order_id=order.id)

    return [c for c in candidates if c.worker_id not in blocked]


def rank_for_order(db: Session, order: Order, cfg: ActiveConfig, blocked: set[int] | None = None) -> list[ScoredWorker]:
    now = now_vn()
    scheduled = bool(order.scheduled_at and order.scheduled_at > now)
    fresh_after = now - timedelta(minutes=settings.location_max_age_minutes) if settings.location_max_age_minutes else None
    candidates = find_candidates(
        db,
        order.latitude,
        order.longitude,
        order.service_id,
        cfg.params.search_radius_km,
        include_busy=scheduled,  # đơn hẹn trước: thợ đang bận việc khác vẫn có thể nhận lịch sau
        fresh_after=fresh_after,
    )
    eligible = filter_eligible(db, order, candidates, blocked)
    return score_candidates(db, eligible, cfg.params)


# ---------- Gửi offer ----------


def _send_offer(db: Session, order: Order, sw: ScoredWorker, cfg: ActiveConfig, round_no: int, mode: str, service_name: str):
    now = now_vn()
    db.add(
        OrderOffer(
            order_id=order.id,
            worker_id=sw.worker.worker_id,
            match_score=round(sw.total, 5),
            distance_km=round(sw.worker.distance_km, 3),
            status="sent",
            sent_at=now,
            expires_at=now + timedelta(seconds=cfg.offer_timeout_seconds),
            round=round_no,
            mode=mode,
        )
    )
    earning = int(order.estimated_price or 0) - ws.commission_of(int(order.estimated_price or 0))
    when = "Hẹn " + order.scheduled_at.strftime("%H:%M %d/%m") if order.scheduled_at else "Làm ngay"
    notify(
        db,
        sw.worker.worker_id,
        f"Đơn mới: {service_name}",
        f"{sw.worker.distance_km:.1f} km · {when} · thực nhận ~{ws.money(earning)}",
        "offer",
        order.id,
    )


def run_instant_wave(db: Session, order_id: int, cfg: ActiveConfig | None = None) -> int:
    """Gửi 1 đợt offer cho đơn (chế độ tức thời). Trả về số offer đã gửi."""
    _lock(db)
    cfg = cfg or load_active_config(db)
    order = db.scalar(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    )
    dispatch = db.get(OrderDispatch, order_id, populate_existing=True)
    if not order or order.status != "pending" or order.worker_id is not None or dispatch is None:
        db.commit()
        return 0
    now = now_vn()
    if _live_offer_exists(db, order.id):
        db.commit()
        return 0

    ranked = rank_for_order(db, order, cfg)
    service_name = db.scalar(select(Service.name).where(Service.id == order.service_id)) or "Dịch vụ điện"
    sent = _send_wave(db, order, dispatch, ranked, cfg, now, service_name)
    db.commit()
    return sent


def _send_wave(
    db: Session, order: Order, dispatch: OrderDispatch, ranked: list[ScoredWorker], cfg: ActiveConfig, now, service_name: str
) -> int:
    """1 đợt kiểu tức thời: gửi offer cho top-k ứng viên đã xếp hạng (chưa commit)."""
    top = ranked[: max(1, cfg.params.max_offers)]
    dispatch.last_attempt_at = now
    dispatch.last_candidates = len(ranked)
    if top:
        dispatch.rounds += 1
        dispatch.offers_sent += len(top)
        order.matching_mode = "instant"
        for sw in top:
            _send_offer(db, order, sw, cfg, dispatch.rounds, "instant", service_name)
        dispatch.next_attempt_at = now + timedelta(seconds=cfg.offer_timeout_seconds)
        log.info("Đơn #%s: đợt %s gửi %s offer (%s ứng viên)", order.id, dispatch.rounds, len(top), len(ranked))
    else:
        dispatch.next_attempt_at = now + timedelta(seconds=settings.dispatch_retry_seconds)
    return len(top)


def run_due_instant(db: Session) -> int:
    _adopt_orphans(db)
    now = now_vn()
    due = db.scalars(
        select(OrderDispatch.order_id)
        .join(Order, Order.id == OrderDispatch.order_id)
        .where(
            OrderDispatch.mode == "instant",
            OrderDispatch.next_attempt_at <= now,
            Order.status == "pending",
            Order.worker_id.is_(None),
        )
        .order_by(OrderDispatch.created_at)
    ).all()
    if not due:
        return 0
    cfg = load_active_config(db)
    sent = 0
    for order_id in due:
        sent += run_instant_wave(db, order_id, cfg)
    return sent


@dataclass
class BatchResult:
    orders: int = 0
    workers: int = 0
    assigned: int = 0
    total_score: float = 0.0
    solve_ms: float = 0.0
    pairs: list[tuple[int, int]] = field(default_factory=list)  # (order_id, worker_id)


def run_batch_round(db: Session, cfg: ActiveConfig | None = None) -> BatchResult:
    """1 lượt ghép theo lô bằng Hungarian cho mọi đơn chế độ batch đang chờ."""
    _lock(db)
    cfg = cfg or load_active_config(db)
    now = now_vn()
    orders = db.scalars(
        select(Order)
        .join(OrderDispatch, OrderDispatch.order_id == Order.id)
        .where(
            OrderDispatch.mode == "batch",
            OrderDispatch.next_attempt_at <= now,
            Order.status == "pending",
            Order.worker_id.is_(None),
            ~exists().where(
                OrderOffer.order_id == Order.id, OrderOffer.status == "sent", OrderOffer.expires_at > now
            ),
        )
        .order_by(Order.id)
        .with_for_update(of=Order, skip_locked=True)
    ).all()
    result = BatchResult(orders=len(orders))
    if not orders:
        db.commit()
        return result

    # Ứng viên hợp lệ + điểm của từng đơn
    per_order = [{s.worker.worker_id: s for s in rank_for_order(db, o, cfg)} for o in orders]
    names = dict(db.execute(select(Service.id, Service.name)).all())
    _assign_hungarian(db, orders, per_order, cfg, now, names, result)
    db.commit()
    if result.orders:
        log.info(
            "Batch: %s đơn x %s thợ -> ghép %s cặp, tổng điểm %.3f, Hungarian %.1f ms",
            result.orders, result.workers, result.assigned, result.total_score, result.solve_ms,
        )
    return result


def _assign_hungarian(
    db: Session,
    orders: list[Order],
    per_order: list[dict[int, ScoredWorker]],
    cfg: ActiveConfig,
    now,
    names: dict[int, str],
    result: BatchResult,
) -> None:
    """Giải bài toán gán đơn x thợ bằng Hungarian, mỗi đơn được gán gửi 1 offer (chưa commit)."""
    worker_ids: list[int] = []
    seen: set[int] = set()
    for cand in per_order:
        for wid in cand:
            if wid not in seen:
                seen.add(wid)
                worker_ids.append(wid)
    result.workers += len(worker_ids)

    matrix = [[(cand[w].total if w in cand else None) for w in worker_ids] for cand in per_order]
    t0 = time.perf_counter()
    pairs = hungarian_max(matrix) if worker_ids else []
    result.solve_ms += (time.perf_counter() - t0) * 1000

    assigned_orders = set()
    for i, j in pairs:
        o, sw = orders[i], per_order[i][worker_ids[j]]
        d = db.get(OrderDispatch, o.id)
        d.rounds += 1
        d.offers_sent += 1
        o.matching_mode = "batch"
        _send_offer(db, o, sw, cfg, d.rounds, "batch", names.get(o.service_id, "Dịch vụ điện"))
        d.next_attempt_at = now + timedelta(seconds=cfg.offer_timeout_seconds)
        assigned_orders.add(o.id)
        result.pairs.append((o.id, sw.worker.worker_id))
        result.total_score += sw.total
    for i, o in enumerate(orders):
        d = db.get(OrderDispatch, o.id)
        d.last_attempt_at = now
        d.last_candidates = len(per_order[i])
        if o.id not in assigned_orders:
            d.next_attempt_at = now  # lượt sau thử lại
    result.assigned += len(pairs)


@dataclass
class AutoResult:
    orders: int = 0
    instant_orders: int = 0  # đơn đứng một mình -> gửi kiểu tức thời
    instant_offers: int = 0
    batch_groups: int = 0  # số nhóm tranh chấp giải bằng Hungarian
    batch: BatchResult = field(default_factory=BatchResult)


def run_auto_round(db: Session, cfg: ActiveConfig | None = None) -> AutoResult:
    """1 nhịp của chế độ auto (hybrid): đơn không tranh thợ -> tức thời top-k; nhóm tranh thợ -> Hungarian."""
    _lock(db)
    cfg = cfg or load_active_config(db)
    now = now_vn()
    orders = db.scalars(
        select(Order)
        .join(OrderDispatch, OrderDispatch.order_id == Order.id)
        .where(
            OrderDispatch.mode == "auto",
            OrderDispatch.next_attempt_at <= now,
            Order.status == "pending",
            Order.worker_id.is_(None),
            ~exists().where(
                OrderOffer.order_id == Order.id, OrderOffer.status == "sent", OrderOffer.expires_at > now
            ),
        )
        .order_by(Order.id)
        .with_for_update(of=Order, skip_locked=True)
    ).all()
    res = AutoResult(orders=len(orders))
    if not orders:
        db.commit()
        return res

    ranked = [rank_for_order(db, o, cfg) for o in orders]
    per_order = [{s.worker.worker_id: s for s in r} for r in ranked]
    names = dict(db.execute(select(Service.id, Service.name)).all())
    groups = competition_groups(per_order)
    for group in groups:
        if len(group) == 1:
            i = group[0]
            o = orders[i]
            d = db.get(OrderDispatch, o.id)
            sent = _send_wave(db, o, d, ranked[i], cfg, now, names.get(o.service_id, "Dịch vụ điện"))
            res.instant_orders += 1
            res.instant_offers += sent
        else:
            res.batch_groups += 1
            _assign_hungarian(db, [orders[i] for i in group], [per_order[i] for i in group], cfg, now, names, res.batch)
    res.batch.orders = sum(len(g) for g in groups if len(g) > 1)
    db.commit()
    if res.batch_groups:
        log.info(
            "Auto: %s đơn -> %s đơn tức thời, %s nhóm tranh chấp (%s đơn) giải Hungarian: ghép %s cặp",
            res.orders, res.instant_orders, res.batch_groups, res.batch.orders, res.batch.assigned,
        )
    return res


# ---------- Hết hạn, quá hạn, nhắc lịch ----------


def expire_offers(db: Session) -> int:
    now = now_vn()
    rows = db.execute(
        update(OrderOffer)
        .where(OrderOffer.status == "sent", OrderOffer.expires_at <= now)
        .values(status="expired", responded_at=now)
        .returning(OrderOffer.order_id)
    ).all()
    order_ids = {r[0] for r in rows}
    if order_ids:
        db.execute(
            update(OrderDispatch)
            .where(OrderDispatch.order_id.in_(order_ids), OrderDispatch.next_attempt_at > now)
            .values(next_attempt_at=now)
        )
    db.commit()
    return len(rows)


def cancel_overdue(db: Session) -> int:
    """Hết thời gian chờ mà chưa có thợ nhận -> hủy đơn, báo khách đặt lại."""
    now = now_vn()
    overdue = db.scalars(
        select(Order)
        .join(OrderDispatch, OrderDispatch.order_id == Order.id)
        .where(Order.status == "pending", Order.worker_id.is_(None), OrderDispatch.deadline_at <= now)
        .with_for_update(of=Order, skip_locked=True)
    ).all()
    for o in overdue:
        o.status = "cancelled"
        o.cancel_reason = "Hệ thống: chưa tìm được thợ phù hợp trong thời gian chờ"
        _history(db, o, "cancelled", None)
        db.execute(
            update(OrderOffer)
            .where(OrderOffer.order_id == o.id, OrderOffer.status == "sent")
            .values(status="expired", responded_at=now)
        )
        notify(
            db,
            o.customer_id,
            "Chưa tìm được thợ",
            f"Rất tiếc, đơn #{o.id} chưa có thợ phù hợp nhận. Bạn vui lòng đặt lại hoặc chọn giờ hẹn khác.",
            "order_cancelled",
            o.id,
        )
    db.commit()
    return len(overdue)


def send_schedule_reminders(db: Session) -> int:
    now = now_vn()
    soon = now + timedelta(minutes=settings.schedule_reminder_minutes)
    orders = db.scalars(
        select(Order).where(
            Order.status == "accepted",
            Order.scheduled_at.is_not(None),
            Order.scheduled_at > now,
            Order.scheduled_at <= soon,
            ~exists().where(
                Notification.type == "schedule_reminder",
                Notification.reference_id == Order.id,
                Notification.user_id == Order.worker_id,
            ),
        )
    ).all()
    for o in orders:
        notify(
            db,
            o.worker_id,
            "Sắp đến giờ hẹn",
            f"Đơn #{o.id} lúc {o.scheduled_at.strftime('%H:%M')} tại {o.address_line}. Nhớ xuất phát sớm nhé!",
            "schedule_reminder",
            o.id,
        )
        ws.refresh_availability(db, o.worker_id)
    db.commit()
    return len(orders)


# ---------- Thợ trả lời offer ----------


def _get_offer(db: Session, worker: User, offer_id: int) -> OrderOffer:
    offer = db.scalar(select(OrderOffer).where(OrderOffer.id == offer_id, OrderOffer.worker_id == worker.id))
    if not offer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy lời mời nhận đơn")
    return offer


def accept_offer(db: Session, worker: User, offer_id: int) -> Order:
    offer = _get_offer(db, worker, offer_id)
    # Khóa đơn trước rồi mới khóa offer (cùng thứ tự với luồng hủy đơn) để tránh deadlock
    order = db.scalar(
        select(Order).where(Order.id == offer.order_id).with_for_update().execution_options(populate_existing=True)
    )
    offer = db.scalar(
        select(OrderOffer).where(OrderOffer.id == offer_id).with_for_update().execution_options(populate_existing=True)
    )
    now = now_vn()

    if offer.status != "sent":
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Lời mời này đã hết hiệu lực")
    if offer.expires_at and offer.expires_at <= now:
        offer.status, offer.responded_at = "expired", now
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "Đã hết thời gian nhận đơn")
    if order.status != "pending" or order.worker_id is not None:
        offer.status, offer.responded_at = "expired", now
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "Đơn đã có thợ khác nhận hoặc khách đã hủy")

    profile = db.get(WorkerProfile, worker.id)
    if not profile or profile.verification_status != "approved":
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hồ sơ chưa được duyệt")
    scheduled = bool(order.scheduled_at and order.scheduled_at > now)
    if not scheduled and ws.has_inflight_instant_job(db, worker.id):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bạn đang có việc chưa xong, hãy hoàn thành trước khi nhận đơn mới")
    when = order.scheduled_at if scheduled else now
    if worker.id in ws.conflicting_workers(db, [worker.id], when, exclude_order_id=order.id):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bạn đã có lịch hẹn khác gần thời điểm này")

    order.worker_id = worker.id
    order.status = "accepted"
    order.accepted_at = now
    _history(db, order, "accepted", worker.id)
    offer.status, offer.responded_at = "accepted", now
    db.execute(
        update(OrderOffer)
        .where(OrderOffer.order_id == order.id, OrderOffer.id != offer.id, OrderOffer.status == "sent")
        .values(status="expired", responded_at=now)
    )
    ws.refresh_availability(db, worker.id)
    when_text = f" (hẹn {order.scheduled_at.strftime('%H:%M %d/%m')})" if order.scheduled_at else ""
    notify(
        db,
        order.customer_id,
        "Đã có thợ nhận đơn",
        f"Thợ {worker.full_name} đã nhận đơn #{order.id}{when_text}.",
        "order_status",
        order.id,
    )
    db.commit()
    db.refresh(order)
    return order


def reject_offer(db: Session, worker: User, offer_id: int, reason: str | None) -> None:
    offer = _get_offer(db, worker, offer_id)
    offer = db.scalar(
        select(OrderOffer).where(OrderOffer.id == offer.id).with_for_update().execution_options(populate_existing=True)
    )
    if offer.status != "sent":
        db.rollback()
        return  # đã hết hạn / đơn đã có người nhận: coi như xong
    now = now_vn()
    offer.status, offer.responded_at, offer.reason = "rejected", now, reason
    order_id = offer.order_id
    db.flush()
    trigger = not _live_offer_exists(db, order_id)
    if trigger:
        db.execute(update(OrderDispatch).where(OrderDispatch.order_id == order_id).values(next_attempt_at=now))
    db.commit()
    if trigger:
        d = db.get(OrderDispatch, order_id)
        if d and d.mode == "instant":
            run_instant_wave(db, order_id)


def withdraw_worker_offers(db: Session, worker_id: int) -> None:
    """Thợ tắt nhận đơn: các offer đang chờ của thợ coi như hết hạn để đơn đi tiếp."""
    now = now_vn()
    rows = db.execute(
        update(OrderOffer)
        .where(OrderOffer.worker_id == worker_id, OrderOffer.status == "sent")
        .values(status="expired", responded_at=now)
        .returning(OrderOffer.order_id)
    ).all()
    ids = {r[0] for r in rows}
    if ids:
        db.execute(update(OrderDispatch).where(OrderDispatch.order_id.in_(ids)).values(next_attempt_at=now))


def requeue_after_worker_cancel(db: Session, order: Order, worker: User, reason: str) -> None:
    """Thợ hủy khi chưa bắt đầu sửa: trả đơn về hàng đợi để tìm thợ khác (không mời lại thợ này)."""
    now = now_vn()
    db.execute(
        update(OrderOffer)
        .where(OrderOffer.order_id == order.id, OrderOffer.worker_id == worker.id)
        .values(status="cancelled", responded_at=now, reason=reason)
    )
    order.worker_id = None
    order.status = "pending"
    order.accepted_at = None
    _history(db, order, "pending", worker.id)
    d = db.get(OrderDispatch, order.id)
    cfg = load_active_config(db)
    if d is None:
        d = OrderDispatch(order_id=order.id, mode=cfg.mode, deadline_at=_deadline(order))
        db.add(d)
    d.next_attempt_at = now
    d.deadline_at = max(d.deadline_at, _deadline(order))
    notify(
        db,
        order.customer_id,
        "Thợ đã hủy nhận đơn",
        f"Đơn #{order.id}: thợ không thể đến ({reason}). Hệ thống đang tìm thợ khác cho bạn.",
        "order_status",
        order.id,
    )
