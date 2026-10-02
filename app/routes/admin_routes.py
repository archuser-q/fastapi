from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.admin import (
    ReviewDocumentRequest,
    UserStatusUpdate,
    WorkerVerificationRequest,
)

admin_only = require_roles("admin")

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(admin_only)],
)


@router.get("/users")
def list_users(
    role: Literal["customer", "worker", "admin"] | None = None,
    user_status: Literal["active", "blocked", "pending"] | None = Query(None, alias="status"),
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return admin_controller.list_users(db, role, user_status, keyword, page, page_size)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    return admin_controller.get_user(db, user_id)


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return admin_controller.update_user_status(db, admin, user_id, data)


@router.get("/workers")
def list_workers(
    verification_status: Literal["pending", "approved", "rejected"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return admin_controller.list_workers(db, verification_status, page, page_size)


@router.get("/workers/{worker_id}")
def get_worker(worker_id: int, db: Session = Depends(get_db)):
    return admin_controller.get_worker(db, worker_id)


@router.patch("/worker-documents/{document_id}/review")
def review_document(
    document_id: int,
    data: ReviewDocumentRequest,
    db: Session = Depends(get_db),
    reviewer: User = Depends(admin_only),
):
    return admin_controller.review_document(db, reviewer, document_id, data)


@router.patch("/workers/{worker_id}/verification")
def update_worker_verification(
    worker_id: int,
    data: WorkerVerificationRequest,
    db: Session = Depends(get_db),
):
    return admin_controller.update_worker_verification(db, worker_id, data)


# ---------- Dashboard (trang Overview) ----------


@router.get("/dashboard/overview")
def get_dashboard_overview(db: Session = Depends(get_db)):
    return admin_controller.get_dashboard_overview(db)


@router.get("/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    return admin_controller.get_dashboard_stats(db)


@router.get("/dashboard/revenue-chart")
def get_dashboard_revenue_chart(
    months: int = Query(9, ge=1, le=24),
    db: Session = Depends(get_db),
):
    return admin_controller.get_dashboard_revenue_chart(db, months)


@router.get("/dashboard/service-breakdown")
def get_dashboard_service_breakdown(db: Session = Depends(get_db)):
    return admin_controller.get_dashboard_service_breakdown(db)


@router.get("/dashboard/worker-activities")
def get_dashboard_worker_activities(
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return admin_controller.get_dashboard_worker_activities(db, limit)


@router.get("/dashboard/top-workers")
def get_dashboard_top_workers(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return admin_controller.get_dashboard_top_workers(db, limit)


@router.get("/dashboard/recent-complaints")
def get_dashboard_recent_complaints(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return admin_controller.get_dashboard_recent_complaints(db, limit)


@router.get("/dashboard/recent-orders")
def get_dashboard_recent_orders(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return admin_controller.get_dashboard_recent_orders(db, limit)