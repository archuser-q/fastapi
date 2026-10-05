from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReviewPerson(BaseModel):
    id: int
    full_name: str
    phone: str
    avatar_url: str | None


class ReviewListItem(BaseModel):
    id: int
    order_id: int
    rating: int
    comment: str | None
    is_flagged: bool
    flag_reason: str | None
    is_hidden: bool
    customer: ReviewPerson
    worker: ReviewPerson
    service_name: str
    created_at: datetime
    moderated_at: datetime | None


class RatingBucket(BaseModel):
    star: int
    count: int
    percent: float


class ReviewStats(BaseModel):
    total: int
    visible: int
    flagged: int
    hidden: int
    low: int
    average: float | None
    distribution: list[RatingBucket]


class ReviewOrder(BaseModel):
    id: int
    status: str
    service_name: str
    category_name: str
    amount: int | None
    completed_at: datetime | None


class ReviewWorkerStats(BaseModel):
    average: float | None
    visible_reviews: int
    low_reviews: int
    flagged_reviews: int
    hidden_reviews: int


class ReviewComplaint(BaseModel):
    id: int
    reason: str
    status: str
    created_at: datetime


class ReviewDetail(ReviewListItem):
    moderation_note: str | None
    moderated_by_name: str | None
    order: ReviewOrder
    worker_stats: ReviewWorkerStats
    complaints: list[ReviewComplaint]


class ReviewModeration(BaseModel):
    action: Literal["flag", "approve", "hide", "restore"]
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_note(self):
        if self.action in ("flag", "hide") and not (self.note or "").strip():
            raise ValueError("Cần nhập lý do khi gắn cờ hoặc ẩn đánh giá")
        return self
