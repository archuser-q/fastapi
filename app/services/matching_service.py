"""Chấm điểm & xếp hạng thợ cho 1 đơn (dùng chung cho điều phối thật và trang mô phỏng của admin).

Quy trình 3 bước:
  1. Lọc thô bằng chỉ mục không gian (geo_service.find_nearby_workers – thành viên C):
     thợ đã duyệt, đang hoạt động, đúng dịch vụ, trong bán kính tìm và bán kính nhận việc của thợ.
  2. Lọc ràng buộc cứng của nghiệp vụ (chỉ khi điều phối thật – xem dispatch_service.filter_eligible).
  3. Chấm điểm Weighted Scoring (app.matching.scoring) rồi sắp xếp giảm dần.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching.scoring import Weights, factor_scores, weighted_total
from app.models import MatchingConfig, Order, Service
from app.schemas.geo import NearbyWorker
from app.services.geo_service import find_nearby_workers
from app.utils.dates import now_vn

ACTIVE_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress")
PRICE_HISTORY_DAYS = 90
CANDIDATE_LIMIT = 200

# Cấu hình dùng khi admin chưa bật cấu hình nào
DEFAULT_CONFIG = {
    "mode": "instant",
    "weight_distance": 0.4,
    "weight_trust": 0.3,
    "weight_price": 0.1,
    "weight_workload": 0.2,
    "batch_window_seconds": 10,
    "search_radius_km": 5.0,
    "max_offers": 3,
    "offer_timeout_seconds": 60,
}


@dataclass
class MatchingParams:
    weight_distance: float
    weight_trust: float
    weight_price: float
    weight_workload: float
    search_radius_km: float
    max_offers: int

    @property
    def weights(self) -> Weights:
        return Weights(
            distance=self.weight_distance,
            trust=self.weight_trust,
            price=self.weight_price,
            workload=self.weight_workload,
        )


@dataclass
class ActiveConfig:
    """Cấu hình đang áp dụng (đọc từ bảng matching_configs, hoặc mặc định)."""

    name: str
    mode: str
    params: MatchingParams
    batch_window_seconds: int
    offer_timeout_seconds: int


@dataclass
class ScoredWorker:
    worker: NearbyWorker
    active_orders: int
    price_ratio: float | None
    scores: dict[str, float]
    contributions: dict[str, float]
    total: float


def load_active_config(db: Session) -> ActiveConfig:
    c = db.scalar(select(MatchingConfig).where(MatchingConfig.is_active.is_(True)))
    if c is None:
        d = DEFAULT_CONFIG
        return ActiveConfig(
            name="Mặc định (chưa có cấu hình)",
            mode=d["mode"],
            params=MatchingParams(
                weight_distance=d["weight_distance"],
                weight_trust=d["weight_trust"],
                weight_price=d["weight_price"],
                weight_workload=d["weight_workload"],
                search_radius_km=d["search_radius_km"],
                max_offers=d["max_offers"],
            ),
            batch_window_seconds=d["batch_window_seconds"],
            offer_timeout_seconds=d["offer_timeout_seconds"],
        )
    return ActiveConfig(
        name=c.name,
        mode=c.mode,
        params=MatchingParams(
            weight_distance=float(c.weight_distance),
            weight_trust=float(c.weight_trust),
            weight_price=float(c.weight_price),
            weight_workload=float(c.weight_workload),
            search_radius_km=float(c.search_radius_km),
            max_offers=c.max_offers,
        ),
        batch_window_seconds=c.batch_window_seconds or DEFAULT_CONFIG["batch_window_seconds"],
        offer_timeout_seconds=c.offer_timeout_seconds,
    )


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


def find_candidates(
    db: Session,
    latitude: float,
    longitude: float,
    service_id: int | None,
    radius_km: float,
    include_busy: bool = False,
    fresh_after: datetime | None = None,
) -> list[NearbyWorker]:
    """Bước 1: lọc ứng viên bằng chỉ mục không gian."""
    return find_nearby_workers(
        db,
        latitude,
        longitude,
        radius_km,
        service_id=service_id,
        statuses=("online", "busy") if include_busy else ("online",),
        fresh_after=fresh_after,
        limit=CANDIDATE_LIMIT,
    )


def score_candidates(db: Session, candidates: list[NearbyWorker], params: MatchingParams) -> list[ScoredWorker]:
    """Bước 3: chấm điểm và sắp xếp (điểm giảm dần, hòa điểm thì ai gần hơn đứng trước)."""
    if not candidates:
        return []
    ids = [c.worker_id for c in candidates]
    active = _active_orders(db, ids)
    ratios = _price_ratios(db, ids)
    weights = params.weights

    scored = []
    for c in candidates:
        ratio = ratios.get(c.worker_id)
        in_progress = active.get(c.worker_id, 0)
        scores = factor_scores(c.distance_km, params.search_radius_km, c.trust_score, ratio, in_progress)
        total, contributions = weighted_total(scores, weights)
        scored.append(
            ScoredWorker(
                worker=c,
                active_orders=in_progress,
                price_ratio=ratio,
                scores=scores,
                contributions=contributions,
                total=total,
            )
        )
    scored.sort(key=lambda s: (-s.total, s.worker.distance_km))
    return scored


def rank_workers(
    db: Session,
    latitude: float,
    longitude: float,
    service_id: int | None,
    params: MatchingParams,
    include_busy: bool = False,
) -> list[ScoredWorker]:
    """Xếp hạng thợ quanh 1 điểm (trang "Mô phỏng" của web quản trị gọi hàm này)."""
    candidates = find_candidates(db, latitude, longitude, service_id, params.search_radius_km, include_busy)
    return score_candidates(db, candidates, params)
