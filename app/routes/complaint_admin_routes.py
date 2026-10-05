from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import complaint_admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.complaint_admin import ComplaintStatusUpdate

admin_only = require_roles("admin")

router = APIRouter(
    prefix="/admin/complaints",
    tags=["Admin - Complaints"],
    dependencies=[Depends(admin_only)],
)


@router.get("")
def list_complaints(
    complaint_status: Literal["open", "processing", "resolved", "rejected"] | None = Query(
        None, alias="status"
    ),
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return complaint_admin_controller.list_complaints(
        db, complaint_status, keyword, date_from, date_to, page, page_size
    )


@router.get("/status-counts")
def get_status_counts(
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return complaint_admin_controller.get_status_counts(db, keyword, date_from, date_to)


@router.get("/{complaint_id}")
def get_complaint(complaint_id: int, db: Session = Depends(get_db)):
    return complaint_admin_controller.get_complaint(db, complaint_id)


@router.patch("/{complaint_id}/status")
def update_complaint_status(
    complaint_id: int,
    data: ComplaintStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return complaint_admin_controller.update_status(db, admin, complaint_id, data)
