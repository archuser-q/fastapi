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