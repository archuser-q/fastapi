"""Schema cho app khách hàng."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


# ---------- Hồ sơ ----------


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    avatar_url: str | None = Field(default=None, max_length=500)

    _strip = field_validator("full_name", "avatar_url")(_clean)


class DeviceTokenCreate(BaseModel):
    token: str = Field(min_length=10, max_length=4096)
    platform: Literal["android", "ios", "web"]


# ---------- Địa chỉ ----------


class AddressCreate(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    address_line: str = Field(min_length=3, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_default: bool = False

    _strip = field_validator("label", "address_line")(_clean)


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    address_line: str | None = Field(default=None, min_length=3, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_default: bool | None = None

    _strip = field_validator("label", "address_line")(_clean)

    @model_validator(mode="after")
    def _pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Phải gửi cả latitude và longitude")
        return self


class AddressOut(BaseModel):
    id: int
    label: str | None
    address_line: str
    latitude: float
    longitude: float
    is_default: bool
    created_at: datetime


# ---------- Danh mục dịch vụ (public) ----------


class CatalogService(BaseModel):
    id: int
    category_id: int
    name: str
    description: str | None
    base_price: int
    unit: str | None


class CatalogCategory(BaseModel):
    id: int
    parent_id: int | None
    name: str
    description: str | None
    icon_url: str | None
    services_count: int


# ---------- Đơn hàng ----------


class OrderCreate(BaseModel):
    service_id: int
    # Dùng địa chỉ đã lưu, hoặc gửi trực tiếp address_line + toạ độ
    address_id: int | None = None
    address_line: str | None = Field(default=None, min_length=3, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = Field(default=None, max_length=2000)
    image_urls: list[str] = Field(default_factory=list, max_length=6)
    scheduled_at: datetime | None = None  # None = đặt ngay
    matching_mode: Literal["instant", "batch"] = "instant"

    _strip = field_validator("address_line", "description")(_clean)

    @model_validator(mode="after")
    def _address(self):
        if self.address_id is None and (
            not self.address_line or self.latitude is None or self.longitude is None
        ):
            raise ValueError("Cần address_id hoặc đủ address_line, latitude, longitude")
        return self


class CancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OrderWorkerBrief(BaseModel):
    id: int
    full_name: str
    phone: str
    avatar_url: str | None
    trust_score: float
    review_count: int
    completed_orders: int


class CustomerOrderItem(BaseModel):
    id: int
    status: str
    service_name: str
    category_name: str
    address_line: str
    scheduled_at: datetime | None
    estimated_price: int | None
    final_price: int | None
    worker: OrderWorkerBrief | None
    created_at: datetime
    completed_at: datetime | None


class HistoryItem(BaseModel):
    status: str
    created_at: datetime


class ExtraQuoteItem(BaseModel):
    id: int
    description: str
    amount: int
    status: str
    created_at: datetime
    responded_at: datetime | None


class PaymentItem(BaseModel):
    id: int
    amount: int
    method: str
    status: str
    transaction_code: str | None
    created_at: datetime
    paid_at: datetime | None


class ReviewItem(BaseModel):
    id: int
    rating: int
    comment: str | None
    created_at: datetime


class WarrantyItem(BaseModel):
    id: int
    order_id: int
    terms: str | None
    start_date: date
    end_date: date
    status: str


class CustomerOrderDetail(CustomerOrderItem):
    service_id: int
    latitude: float
    longitude: float
    description: str | None
    image_urls: list[str]
    matching_mode: str | None
    cancel_reason: str | None
    accepted_at: datetime | None
    total_amount: int | None
    history: list[HistoryItem]
    extra_quotes: list[ExtraQuoteItem]
    payments: list[PaymentItem]
    review: ReviewItem | None
    warranty: WarrantyItem | None
    can_cancel: bool
    can_pay: bool
    can_review: bool


class TrackingOut(BaseModel):
    order_id: int
    status: str
    destination_latitude: float
    destination_longitude: float
    worker_latitude: float | None
    worker_longitude: float | None
    location_updated_at: datetime | None


# ---------- Chat ----------


class MessageCreate(BaseModel):
    content: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)

    _strip = field_validator("content", "image_url")(_clean)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.content and not self.image_url:
            raise ValueError("Tin nhắn không được trống")
        return self


class MessageOut(BaseModel):
    id: int
    sender_id: int
    is_mine: bool
    content: str | None
    image_url: str | None
    is_read: bool
    created_at: datetime


# ---------- Thanh toán ----------


class PaymentCreate(BaseModel):
    method: Literal["cash", "momo", "vnpay"]


class PaymentOut(PaymentItem):
    order_id: int
    pay_url: str | None = None  # Link thanh toán sandbox (sẽ gắn MoMo/VNPay sau)


# ---------- Đánh giá, khiếu nại, bảo hành ----------


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)

    _strip = field_validator("comment")(_clean)


class ComplaintCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("reason", "description")(_clean)


class ComplaintOut(BaseModel):
    id: int
    order_id: int
    reason: str
    description: str | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class WarrantyClaim(BaseModel):
    description: str = Field(min_length=3, max_length=2000)


# ---------- Hồ sơ thợ (khách xem) ----------


class PublicReview(BaseModel):
    rating: int
    comment: str | None
    customer_name: str
    created_at: datetime


class WorkerPublicProfile(BaseModel):
    id: int
    full_name: str
    avatar_url: str | None
    bio: str | None
    experience_years: int
    trust_score: float
    review_count: int
    completed_orders: int
    services: list[str]
    recent_reviews: list[PublicReview]


# ---------- Thông báo ----------


class NotificationOut(BaseModel):
    id: int
    title: str
    body: str | None
    type: str | None
    reference_id: int | None
    is_read: bool
    created_at: datetime


# ---------- Danh sách của tôi ----------


class MyReviewItem(BaseModel):
    id: int
    order_id: int
    worker_id: int
    worker_name: str
    service_name: str
    rating: int
    comment: str | None
    created_at: datetime


class MyPaymentItem(PaymentItem):
    order_id: int
    service_name: str
