from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Period = Literal["today", "7d", "30d", "month"]
Severity = Literal["high", "medium", "low", "none"]


# ---------- System summary ----------


class UsersSummary(BaseModel):
    customers: int
    workers: int
    admins: int
    blocked: int
    new_customers_month: int
    new_workers_month: int


class WorkersSummary(BaseModel):
    pending: int
    approved: int
    rejected: int
    online: int
    busy: int
    offline: int
    pending_documents: int


class StatusCount(BaseModel):
    status: str
    label: str
    count: int


class OrdersSummary(BaseModel):
    total: int
    waiting: int
    active: int
    completed_today: int
    cancelled_today: int
    by_status: list[StatusCount]


class ComplaintsSummary(BaseModel):
    open: int
    processing: int
    resolved: int
    rejected: int
    avg_resolution_hours: float | None


class RatingBucket(BaseModel):
    star: int
    count: int
    percent: float


class ReviewsSummary(BaseModel):
    total: int
    average: float | None
    flagged: int
    distribution: list[RatingBucket]


class MethodShare(BaseModel):
    method: str
    count: int
    amount: int


class PaymentsSummary(BaseModel):
    success_today_amount: int
    success_month_amount: int
    commission_month_amount: int
    pending: int
    failed_month: int
    by_method_month: list[MethodShare]


class CatalogSummary(BaseModel):
    categories_active: int
    services_active: int
    services_inactive: int


class MatchingConfigBrief(BaseModel):
    id: int
    name: str
    mode: str
    weight_distance: float
    weight_trust: float
    weight_price: float
    weight_workload: float
    batch_window_seconds: int | None
    updated_at: datetime


class SystemSummary(BaseModel):
    generated_at: datetime
    users: UsersSummary
    workers: WorkersSummary
    orders: OrdersSummary
    complaints: ComplaintsSummary
    reviews: ReviewsSummary
    payments: PaymentsSummary
    catalog: CatalogSummary
    matching: MatchingConfigBrief | None


# ---------- Pending tasks ----------


class PendingTask(BaseModel):
    key: str
    title: str
    count: int
    overdue: int
    sla_minutes: int | None
    oldest_at: datetime | None
    severity: Severity
    link: str


class PendingTasks(BaseModel):
    total: int
    total_overdue: int
    items: list[PendingTask]


# ---------- KPIs ----------


class KpiValue(BaseModel):
    value: int | float | None
    previous: int | float | None
    change: int | float | None
    change_percent: float | None


class DashboardKpis(BaseModel):
    period: Period
    start: datetime
    end: datetime
    orders_created: KpiValue
    orders_completed: KpiValue
    completion_rate: KpiValue
    cancellation_rate: KpiValue
    avg_match_minutes: KpiValue
    avg_service_minutes: KpiValue
    offer_acceptance_rate: KpiValue
    revenue: KpiValue
    commission: KpiValue
    avg_order_value: KpiValue
    new_customers: KpiValue
    new_workers: KpiValue
    avg_rating: KpiValue


# ---------- Orders by hour ----------


class HourlyPoint(BaseModel):
    hour: int
    label: str
    orders: int
    previous_orders: int


class OrdersByHour(BaseModel):
    date: str
    compare_date: str
    total: int
    previous_total: int
    peak_hour: int | None
    points: list[HourlyPoint]


# ---------- Quick view (gộp) ----------


class QuickView(BaseModel):
    summary: SystemSummary
    pending_tasks: PendingTasks
    kpis: DashboardKpis
