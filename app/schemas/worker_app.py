"""Schema cho App Thợ (Thành viên B)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split()) if "\n" not in value else value.strip()
    return value or None


# =====================================================================
# Hồ sơ, kỹ năng, giấy tờ, lịch làm việc, ngân hàng
# =====================================================================


class WorkerProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, pattern=r"^0\d{9}$")
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=1000)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    service_radius_km: float | None = Field(default=None, ge=1, le=30)

    _strip = field_validator("full_name", "bio", "avatar_url")(_clean)


class WorkerSkillsUpdate(BaseModel):
    service_ids: list[int] = Field(min_length=1, max_length=50)


class WorkerSkill(BaseModel):
    service_id: int
    name: str
    category_id: int
    category_name: str
    base_price: int
    unit: str | None


class WorkerDocumentCreate(BaseModel):
    doc_type: Literal["id_card_front", "id_card_back", "certificate", "portrait"]
    file_url: str = Field(min_length=5, max_length=500)


class BankAccountIn(BaseModel):
    bank_name: str = Field(min_length=2, max_length=100)
    account_number: str = Field(pattern=r"^\d{6,20}$")
    account_holder: str = Field(min_length=2, max_length=150)

    @field_validator("account_holder")
    @classmethod
    def _upper(cls, v: str) -> str:
        return " ".join(v.split()).upper()

    _strip = field_validator("bank_name")(_clean)


class BankAccountOut(BankAccountIn):
    updated_at: datetime


class OnboardingStatus(BaseModel):
    verification_status: str
    submitted_at: datetime | None
    has_phone: bool
    has_skills: bool
    documents: dict[str, str | None]  # doc_type -> trạng thái giấy tờ mới nhất (None = chưa gửi)
    reject_reasons: list[str]
    missing: list[str]  # các việc còn thiếu (câu tiếng Việt để app hiện)
    can_submit: bool


class WorkerProfileData(BaseModel):
    bio: str | None
    experience_years: int
    service_radius_km: float
    availability: str
    verification_status: str
    trust_score: float
    review_count: int
    completed_orders: int
    rating_avg: float | None
    current_latitude: float | None
    current_longitude: float | None
    location_updated_at: datetime | None
    submitted_at: datetime | None
    level: "WorkerLevel"


class AppSettings(BaseModel):
    commission_rate: float
    min_withdrawal: int
    wallet_debt_limit: int
    location_max_age_minutes: int
    warranty_days: int


class WorkerMe(BaseModel):
    user: UserOut
    profile: WorkerProfileData
    skills: list[WorkerSkill]
    documents: list[WorkerDocumentOut]
    bank_account: BankAccountOut | None
    onboarding: OnboardingStatus
    settings: AppSettings


# =====================================================================
# Nhận đơn, trạng thái, vị trí
# =====================================================================


class AvailabilityUpdate(BaseModel):
    online: bool
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Phải gửi cả latitude và longitude")
        return self


class AvailabilityOut(BaseModel):
    availability: str
    location_fresh: bool


class OfferOut(BaseModel):
    id: int
    order_id: int
    status: str
    round: int
    mode: str | None
    sent_at: datetime
    expires_at: datetime | None
    expires_in_seconds: int
    timeout_seconds: int
    match_score: float | None
    distance_km: float | None
    service_id: int
    service_name: str
    category_name: str
    description: str | None
    image_urls: list[str]
    address_line: str
    latitude: float
    longitude: float
    scheduled_at: datetime | None
    estimated_price: int | None
    estimated_earning: int | None
    commission_rate: float
    customer_name: str


class RejectOfferRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)

    _strip = field_validator("reason")(_clean)


class JobItem(BaseModel):
    id: int
    status: str
    service_name: str
    category_name: str
    address_line: str
    latitude: float
    longitude: float
    scheduled_at: datetime | None
    created_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    estimated_price: int | None
    final_price: int | None
    total_amount: int | None
    customer_name: str
    paid: bool
    payment_method: str | None
    net_earning: int | None
    unread_messages: int
    # Số sao khách đánh giá (đơn đã hoàn thành, đánh giá không bị admin ẩn)
    rating: int | None = None


class JobCustomer(BaseModel):
    id: int
    full_name: str
    phone: str | None  # chỉ hiện khi thợ đang phụ trách đơn
    avatar_url: str | None


class JobHistory(BaseModel):
    status: str
    created_at: datetime


class JobPhoto(BaseModel):
    id: int
    kind: str
    url: str
    created_at: datetime


class JobQuote(BaseModel):
    id: int
    description: str
    amount: int
    status: str
    created_at: datetime
    responded_at: datetime | None


class JobPayment(BaseModel):
    id: int
    amount: int
    method: str
    status: str
    transaction_code: str | None
    created_at: datetime
    paid_at: datetime | None


class JobReview(BaseModel):
    rating: int
    comment: str | None
    created_at: datetime


class JobWarranty(BaseModel):
    terms: str | None
    start_date: date
    end_date: date
    status: str


class JobEarning(BaseModel):
    gross_amount: int
    commission_amount: int
    net_amount: int


class JobDetail(JobItem):
    service_id: int
    description: str | None
    image_urls: list[str]
    cancel_reason: str | None
    customer: JobCustomer
    distance_km: float | None
    history: list[JobHistory]
    photos: list[JobPhoto]
    extra_quotes: list[JobQuote]
    payments: list[JobPayment]
    review: JobReview | None
    warranty: JobWarranty | None
    earning: JobEarning | None
    estimated_earning: int | None
    # Các hành động thợ được làm ở trạng thái hiện tại (app dựa vào đây để hiện nút)
    next_status: str | None
    next_action: str | None
    can_cancel: bool
    cancel_requeues: bool  # True: hủy xong đơn được giao thợ khác; False: hủy luôn đơn
    can_quote: bool
    can_add_photos: bool
    can_confirm_cash: bool
    can_chat: bool
    can_report: bool
    needs_after_photo: bool
    needs_safety_check: bool
    safety_checked_at: datetime | None
    # Đơn hẹn trước còn xa giờ hẹn: thời điểm sớm nhất được bắt đầu di chuyển (None = đi được ngay)
    start_available_at: datetime | None = None
    has_pending_quote: bool
    amount_to_collect: int | None


class AdvanceStatusRequest(BaseModel):
    status: Literal["on_the_way", "arrived", "in_progress", "completed"]
    # Bắt buộc khi chuyển sang "in_progress": thợ xác nhận đã làm đủ checklist an toàn điện trên app
    safety_confirmed: bool = False


class WorkerCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    _strip = field_validator("reason")(_clean)


class PhotoCreate(BaseModel):
    kind: Literal["before", "after"]
    urls: list[str] = Field(min_length=1, max_length=6)


class ExtraQuoteCreate(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    amount: int = Field(gt=0, le=50_000_000)

    _strip = field_validator("description")(_clean)


class WorkerReportCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("reason", "description")(_clean)


class WorkerReportOut(BaseModel):
    id: int
    order_id: int
    reason: str
    description: str | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


# =====================================================================
# Trang chủ
# =====================================================================


class TodayStats(BaseModel):
    completed: int
    net_income: int
    gross_income: int


class WorkerLevel(BaseModel):
    key: str
    name: str
    completed: int
    next_name: str | None
    next_jobs: int | None
    next_rating: float | None
    progress: float


class GeoPoint(BaseModel):
    latitude: float
    longitude: float
    updated_at: datetime | None


class HomeOut(BaseModel):
    availability: str
    verification_status: str
    can_go_online: bool
    blockers: list[str]
    location_fresh: bool
    today: TodayStats
    rating_avg: float | None
    review_count: int
    trust_score: float
    wallet_balance: int
    wallet_restricted: bool
    current_offer: OfferOut | None
    active_job: JobItem | None
    upcoming: list[JobItem]
    unread_notifications: int
    matching_mode: str
    location: GeoPoint | None
    service_radius_km: float
    level: WorkerLevel
    week: TodayStats


# =====================================================================
# Thu nhập, ví
# =====================================================================


class EarningPoint(BaseModel):
    key: str
    label: str
    net: int
    orders: int


class EarningTotals(BaseModel):
    orders: int
    gross: int
    commission: int
    net: int
    cash_collected: int
    online_received: int
    avg_net_per_order: int


class EarningSummary(BaseModel):
    period: str
    label: str
    start: datetime
    end: datetime
    totals: EarningTotals
    previous_net: int
    change_percent: float | None
    chart: list[EarningPoint]
    unpaid_orders: int
    unpaid_amount: int


class EarningItem(BaseModel):
    order_id: int
    service_name: str
    gross_amount: int
    commission_amount: int
    net_amount: int
    payment_method: str | None
    created_at: datetime


class WalletTx(BaseModel):
    id: int
    type: str
    amount: int
    description: str | None
    order_id: int | None
    created_at: datetime


class WalletOut(BaseModel):
    balance: int
    available_for_withdrawal: int
    debt_limit: int
    restricted: bool
    min_withdrawal: int
    pending_withdrawal: int
    bank_account: BankAccountOut | None
    recent: list[WalletTx]


class WithdrawalCreate(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)


class WithdrawalOut(BaseModel):
    id: int
    amount: int
    bank_name: str
    account_number: str
    account_holder: str
    status: str
    transaction_code: str | None
    note: str | None
    created_at: datetime
    processed_at: datetime | None


class TopupCreate(BaseModel):
    amount: int = Field(ge=10_000, le=10_000_000)
    method: Literal["momo", "vnpay"] = "momo"


# =====================================================================
# Đánh giá, hiệu suất
# =====================================================================


class ReviewOut(BaseModel):
    id: int
    order_id: int
    rating: int
    comment: str | None
    customer_name: str
    service_name: str
    created_at: datetime


class ReviewSummary(BaseModel):
    rating_avg: float | None
    review_count: int
    distribution: dict[int, int]


class PerformanceOut(BaseModel):
    period_days: int
    offers_received: int
    offers_accepted: int
    offers_rejected: int
    offers_expired: int
    acceptance_rate: float | None
    jobs_completed: int
    jobs_cancelled_by_worker: int
    completion_rate: float | None
    rating_avg: float | None
    review_count: int
    trust_score: float
    total_completed: int
    total_net: int


WorkerProfileData.model_rebuild()
