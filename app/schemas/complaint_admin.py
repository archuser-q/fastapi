from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ComplaintPerson(BaseModel):
    id: int
    full_name: str
    phone: str
    role: str
    avatar_url: str | None


class ComplaintListItem(BaseModel):
    id: int
    order_id: int
    reason: str
    status: str
    complainant: ComplaintPerson
    worker_name: str | None
    service_name: str
    handled_by_name: str | None
    created_at: datetime
    resolved_at: datetime | None


class StatusCount(BaseModel):
    status: str
    count: int


class ComplaintStatusCounts(BaseModel):
    total: int
    items: list[StatusCount]


class ComplaintOrder(BaseModel):
    id: int
    status: str
    service_name: str
    category_name: str
    amount: int | None
    address_line: str
    customer: ComplaintPerson
    worker: ComplaintPerson | None
    created_at: datetime
    completed_at: datetime | None


class ComplaintOrderReview(BaseModel):
    rating: int
    comment: str | None


class ComplaintHistoryStats(BaseModel):
    worker_total: int
    worker_resolved: int
    complainant_total: int


class ComplaintDetail(BaseModel):
    id: int
    reason: str
    description: str | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None
    complainant: ComplaintPerson
    handled_by: ComplaintPerson | None
    order: ComplaintOrder
    review: ComplaintOrderReview | None
    history: ComplaintHistoryStats


class ComplaintStatusUpdate(BaseModel):
    status: Literal["processing", "resolved", "rejected"]
    resolution: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def check_resolution(self):
        if self.status in ("resolved", "rejected") and not (self.resolution or "").strip():
            raise ValueError("Cần nhập kết quả xử lý khi giải quyết hoặc từ chối khiếu nại")
        return self
