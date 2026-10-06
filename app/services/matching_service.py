"""Thuật toán ghép thợ.

Bước 1, lọc ứng viên: geo_service.find_nearby_workers dùng chỉ mục GiST của PostGIS,
lấy thợ đã duyệt, đang trực tuyến, làm dịch vụ đó, trong bán kính tìm kiếm.

Bước 2, chấm điểm: mỗi ứng viên có 4 điểm thành phần trong khoảng [0, 1]:

  distance  = 1 - d / R                d: khoảng cách tới khách, R: bán kính tìm
  trust     = trust_score              điểm tin cậy của thợ
  price     = min(1, max(0, 2 - r))    r: tỉ lệ trung bình giá chốt / giá gốc của thợ
                                       trong 90 ngày (r <= 1 được 1 điểm, r >= 2 được 0).
                                       Thợ chưa có đơn hoàn thành nhận 0,5 (trung tính)
  workload  = 1 - min(a, 3) / 3        a: số đơn thợ đang làm dở

  Điểm tổng = w_distance*distance + w_trust*trust + w_price*price + w_workload*workload
  với 4 trọng số lấy từ matching_configs, tổng bằng 1, nên điểm tổng cũng nằm trong [0, 1].

Xếp hạng theo điểm tổng giảm dần, bằng điểm thì ưu tiên thợ gần hơn.
Chế độ tức thời: max_offers thợ đứng đầu nhận offer cùng lúc.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, Service
from app.schemas.geo import NearbyWorker
from app.services.geo_service import find_nearby_workers
from app.utils.dates import now_vn

ACTIVE_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress")
PRICE_HISTORY_DAYS = 90
NEUTRAL_PRICE_SCORE = 0.5
MAX_WORKLOAD = 3
CANDIDATE_LIMIT = 200


@dataclass
class MatchingParams:
    weight_distance: float
    weight_trust: float
    weight_price: float
    weight_workload: float
    search_radius_km: float
    max_offers: int


@dataclass
class ScoredWorker:
    worker: NearbyWorker
    active_orders: int
    price_ratio: float | None
    scores: dict[str, float]
    contributions: dict[str, float]
    total: float


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _active_orders(db: Session, worker_ids: list[int]) -> dict[int, int]:
    rows = db.execute(
        select(Order.worker_id, func.count())
        .where(Order.worker_id.in_(worker_ids), Order.status.in_(ACTIVE_STATUSES))
        .group_by(Order.worker_id)
    ).all()
    return dict(rows)


def _price_ratios(db: Session, worker_ids: list[int]) -> dict[int, float]:
    since = now_vn() - timedelta(days=PRICE_HISTORY_DAYS)
    rows = db.execute(
        select(Order.worker_id, func.avg(Order.final_price / Service.base_price))
        .join(Service, Service.id == Order.service_id)
        .where(
            Order.worker_id.in_(worker_ids),
            Order.status == "completed",
            Order.final_price.is_not(None),
            Order.completed_at >= since,
        )
        .group_by(Order.worker_id)
    ).all()
    return {worker_id: float(ratio) for worker_id, ratio in rows}


def rank_workers(
    db: Session,
    latitude: float,
    longitude: float,
    service_id: int | None,
    params: MatchingParams,
    include_busy: bool = False,
) -> list[ScoredWorker]:
    # Bước 1: lọc ứng viên bằng chỉ mục không gian
    candidates = find_nearby_workers(
        db,
        latitude,
        longitude,
        params.search_radius_km,
        service_id=service_id,
        statuses=("online", "busy") if include_busy else ("online",),
        limit=CANDIDATE_LIMIT,
    )
    if not candidates:
        return []

    # Bước 2: chấm điểm
    ids = [c.worker_id for c in candidates]
    active = _active_orders(db, ids)
    ratios = _price_ratios(db, ids)
    weights = {
        "distance": params.weight_distance,
        "trust": params.weight_trust,
        "price": params.weight_price,
        "workload": params.weight_workload,
    }

    scored = []
    for c in candidates:
        ratio = ratios.get(c.worker_id)
        orders_in_progress = active.get(c.worker_id, 0)
        scores = {
            "distance": _clamp(1 - c.distance_km / params.search_radius_km),
            "trust": _clamp(c.trust_score),
            "price": NEUTRAL_PRICE_SCORE if ratio is None else _clamp(2 - ratio),
            "workload": 1 - min(orders_in_progress, MAX_WORKLOAD) / MAX_WORKLOAD,
        }
        contributions = {k: weights[k] * v for k, v in scores.items()}
        scored.append(
            ScoredWorker(
                worker=c,
                active_orders=orders_in_progress,
                price_ratio=ratio,
                scores=scores,
                contributions=contributions,
                total=sum(contributions.values()),
            )
        )

    scored.sort(key=lambda s: (-s.total, s.worker.distance_km))
    return scored
