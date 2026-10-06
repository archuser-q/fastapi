from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

WEIGHT_FIELDS = ("weight_distance", "weight_trust", "weight_price", "weight_workload")


class Weights(BaseModel):
    weight_distance: float = Field(ge=0, le=1)
    weight_trust: float = Field(ge=0, le=1)
    weight_price: float = Field(ge=0, le=1)
    weight_workload: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_sum(self):
        total = sum(getattr(self, f) for f in WEIGHT_FIELDS)
        if abs(total - 1) > 0.001:
            raise ValueError(f"Tổng 4 trọng số phải bằng 1 (hiện là {total:.3f})")
        return self


class MatchingConfigItem(BaseModel):
    id: int
    name: str
    mode: str
    weight_distance: float
    weight_trust: float
    weight_price: float
    weight_workload: float
    batch_window_seconds: int | None
    search_radius_km: float
    max_offers: int
    offer_timeout_seconds: int
    is_active: bool
    updated_by_name: str | None
    updated_at: datetime


class MatchingConfigCreate(Weights):
    name: str = Field(min_length=2, max_length=100)
    mode: Literal["instant", "batch"]
    batch_window_seconds: int | None = Field(default=None, ge=5, le=600)
    search_radius_km: float = Field(default=5, gt=0, le=50)
    max_offers: int = Field(default=3, ge=1, le=20)
    offer_timeout_seconds: int = Field(default=60, ge=10, le=600)

    @model_validator(mode="after")
    def check_batch(self):
        if self.mode == "batch" and not self.batch_window_seconds:
            raise ValueError("Chế độ ghép theo lô cần thời gian gom đơn (batch_window_seconds)")
        if self.mode == "instant":
            self.batch_window_seconds = None
        return self


class MatchingConfigUpdate(MatchingConfigCreate):
    """Sửa cấu hình: gửi lại đầy đủ các trường, để luôn kiểm tra được tổng trọng số."""


class SimulateRequest(BaseModel):
    # Lấy vị trí và dịch vụ từ một đơn có sẵn, hoặc nhập trực tiếp
    order_id: int | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    service_id: int | None = None
    # Mặc định dùng cấu hình đang áp dụng; truyền config_id để thử cấu hình khác
    config_id: int | None = None
    # Thử trọng số khác mà không cần lưu cấu hình
    weights: Weights | None = None
    search_radius_km: float | None = Field(default=None, gt=0, le=50)
    include_busy: bool = False

    @model_validator(mode="after")
    def check_target(self):
        if self.order_id is None and (self.latitude is None or self.longitude is None):
            raise ValueError("Cần chọn một đơn hàng hoặc nhập vĩ độ, kinh độ")
        return self


class ScoreParts(BaseModel):
    distance: float
    trust: float
    price: float
    workload: float


class RankedWorker(BaseModel):
    rank: int
    worker_id: int
    full_name: str
    phone: str
    availability: str
    distance_km: float
    active_orders: int
    price_ratio: float | None
    scores: ScoreParts
    contributions: ScoreParts
    total_score: float
    will_receive_offer: bool


class SimulateTarget(BaseModel):
    order_id: int | None
    latitude: float
    longitude: float
    service_id: int | None
    service_name: str | None


class SimulateResult(BaseModel):
    target: SimulateTarget
    config_name: str
    mode: str
    weights: Weights
    search_radius_km: float
    max_offers: int
    candidates_found: int
    ranking: list[RankedWorker]
