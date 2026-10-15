"""Hàm điểm phù hợp giữa 1 đơn và 1 thợ — Weighted Scoring.

    S(thợ, đơn) = w_d * s_distance + w_t * s_trust + w_p * s_price + w_l * s_workload
    với mỗi s_k thuộc [0, 1] và  w_d + w_t + w_p + w_l = 1  =>  S thuộc [0, 1].

Các tiêu chí (khớp với mô tả ở web quản trị – components/matching/factors.ts):
  s_distance = 1 - d / R                    d: khoảng cách Haversine/PostGIS (km), R: bán kính tìm
  s_trust    = trust_score                  điểm tin cậy 0..1 (thuật toán Trust Score – thành viên A)
  s_price    = clamp(2 - r)                 r: trung bình (giá chốt / giá gốc) 90 ngày; chưa có lịch sử = 0.5
  s_workload = 1 - min(k, 3) / 3            k: số đơn đang làm dở

Các hàm ở đây là hàm thuần (không đụng DB) để dùng chung cho API, mô phỏng và thực nghiệm.
"""

from dataclasses import dataclass

FACTORS = ("distance", "trust", "price", "workload")
NEUTRAL_PRICE_SCORE = 0.5
MAX_WORKLOAD = 3


@dataclass(frozen=True)
class Weights:
    distance: float
    trust: float
    price: float
    workload: float

    def as_dict(self) -> dict[str, float]:
        return {"distance": self.distance, "trust": self.trust, "price": self.price, "workload": self.workload}


DEFAULT_WEIGHTS = Weights(distance=0.4, trust=0.3, price=0.1, workload=0.2)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def factor_scores(
    distance_km: float,
    radius_km: float,
    trust_score: float,
    price_ratio: float | None,
    active_orders: int,
) -> dict[str, float]:
    """Điểm từng tiêu chí, đã chuẩn hóa về [0, 1]."""
    return {
        "distance": clamp01(1 - distance_km / radius_km) if radius_km > 0 else 0.0,
        "trust": clamp01(trust_score),
        "price": NEUTRAL_PRICE_SCORE if price_ratio is None else clamp01(2 - price_ratio),
        "workload": 1 - min(max(active_orders, 0), MAX_WORKLOAD) / MAX_WORKLOAD,
    }


def weighted_total(scores: dict[str, float], weights: Weights) -> tuple[float, dict[str, float]]:
    """Trả về (tổng điểm, phần đóng góp của từng tiêu chí = trọng số x điểm)."""
    w = weights.as_dict()
    contributions = {k: w[k] * scores[k] for k in FACTORS}
    return sum(contributions.values()), contributions


def match_score(
    distance_km: float,
    radius_km: float,
    trust_score: float,
    price_ratio: float | None,
    active_orders: int,
    weights: Weights = DEFAULT_WEIGHTS,
) -> float:
    total, _ = weighted_total(factor_scores(distance_km, radius_km, trust_score, price_ratio, active_orders), weights)
    return total
