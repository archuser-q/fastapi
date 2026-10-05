from datetime import datetime

from pydantic import BaseModel, Field


class OrderPerson(BaseModel):
    id: int
    full_name: str
    phone: str
    avatar_url: str | None


class OrderListItem(BaseModel):
    id: int
    status: str
    customer: OrderPerson
    worker: OrderPerson | None
    service_name: str
    category_name: str
    address_line: str
    amount: int | None
    matching_mode: str | None
    scheduled_at: datetime | None
    created_at: datetime
    completed_at: datetime | None
    has_open_complaint: bool


class StatusCount(BaseModel):
    status: str
    count: int


class OrderStatusCounts(BaseModel):
    total: int
    items: list[StatusCount]


class CategoryOption(BaseModel):
    id: int
    name: str


class OrderFilterOptions(BaseModel):
    categories: list[CategoryOption]


class OrderService(BaseModel):
    id: int
    name: str
    category_name: str
    base_price: int


class OrderWorker(OrderPerson):
    trust_score: float


class OrderHistoryItem(BaseModel):
    status: str
    changed_by_name: str | None
    changed_by_role: str | None
    created_at: datetime


class OrderOfferItem(BaseModel):
    id: int
    worker_id: int
    worker_name: str
    match_score: float | None
    distance_km: float | None
    status: str
    sent_at: datetime
    responded_at: datetime | None


class OrderExtraQuoteItem(BaseModel):
    id: int
    description: str
    amount: int
    status: str
    created_at: datetime
    responded_at: datetime | None


class OrderPaymentItem(BaseModel):
    id: int
    amount: int
    method: str
    status: str
    transaction_code: str | None
    created_at: datetime
    paid_at: datetime | None


class OrderEarning(BaseModel):
    gross_amount: int
    commission_amount: int
    net_amount: int


class OrderReview(BaseModel):
    rating: int
    comment: str | None
    is_flagged: bool
    flag_reason: str | None
    created_at: datetime


class OrderComplaintItem(BaseModel):
    id: int
    reason: str
    status: str
    created_at: datetime
    resolved_at: datetime | None


class OrderDetail(BaseModel):
    id: int
    status: str
    matching_mode: str | None
    address_line: str
    latitude: float
    longitude: float
    description: str | None
    image_urls: list[str]
    scheduled_at: datetime | None
    created_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    cancel_reason: str | None
    estimated_price: int | None
    final_price: int | None
    service: OrderService
    customer: OrderPerson
    worker: OrderWorker | None
    history: list[OrderHistoryItem]
    offers: list[OrderOfferItem]
    extra_quotes: list[OrderExtraQuoteItem]
    payments: list[OrderPaymentItem]
    earning: OrderEarning | None
    review: OrderReview | None
    complaints: list[OrderComplaintItem]


class CancelOrderRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
