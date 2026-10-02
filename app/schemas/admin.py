from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut, WorkerProfileOut


class UserStatusUpdate(BaseModel):
    status: Literal["active", "blocked"]


class ReviewDocumentRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reject_reason: str | None = None

    @model_validator(mode="after")
    def check_reason(self):
        if self.status == "rejected" and not self.reject_reason:
            raise ValueError("Cần nhập lý do từ chối")
        return self


class WorkerVerificationRequest(BaseModel):
    status: Literal["approved", "rejected"]


class AdminWorkerItem(BaseModel):
    user: UserOut
    profile: WorkerProfileOut


class AdminWorkerDetail(BaseModel):
    user: UserOut
    profile: WorkerProfileOut
    documents: list[WorkerDocumentOut]


# ---------- Overview (dashboard) ----------


class GrowthStat(BaseModel):
    value: int
    previous: int
    change_percent: float | None


class OnlineWorkersStat(BaseModel):
    online: int
    busy: int
    total_approved: int


class SatisfactionStat(BaseModel):
    score: float | None
    previous: float | None
    change: float | None
    review_count: int


class DashboardStats(BaseModel):
    revenue_month: GrowthStat
    orders_today: GrowthStat
    online_workers: OnlineWorkersStat
    satisfaction: SatisfactionStat


class MonthlyPoint(BaseModel):
    month: str
    label: str
    revenue: int
    orders: int


class ServiceShare(BaseModel):
    category_id: int
    name: str
    orders: int
    percent: float


class WorkerActivity(BaseModel):
    worker_id: int
    worker_name: str
    avatar_url: str | None
    order_id: int
    status: str
    action: str
    created_at: datetime


class TopWorker(BaseModel):
    user_id: int
    full_name: str
    avatar_url: str | None
    trust_score: float
    avg_rating: float | None
    review_count: int
    completed_orders: int


class RecentComplaint(BaseModel):
    id: int
    order_id: int
    complainant_name: str
    reason: str
    status: str
    created_at: datetime


class RecentComplaints(BaseModel):
    total_open: int
    items: list[RecentComplaint]


class RecentOrder(BaseModel):
    id: int
    customer_name: str
    worker_name: str | None
    service_name: str
    status: str
    amount: int | None
    created_at: datetime


class DashboardOverview(BaseModel):
    stats: DashboardStats
    revenue_chart: list[MonthlyPoint]
    service_breakdown: list[ServiceShare]
    worker_activities: list[WorkerActivity]
    top_workers: list[TopWorker]
    recent_complaints: RecentComplaints
    recent_orders: list[RecentOrder]