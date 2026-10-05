from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import review_admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.review_admin import ReviewModeration

admin_only = require_roles("admin")

router = APIRouter(
    prefix="/admin/reviews",
    tags=["Admin - Reviews"],
    dependencies=[Depends(admin_only)],
)


@router.get("")
def list_reviews(
    view: Literal["flagged", "low", "hidden"] | None = None,
    rating: int | None = Query(None, ge=1, le=5),
    keyword: str | None = None,
    worker_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["newest", "lowest"] = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return review_admin_controller.list_reviews(
        db, view, rating, keyword, worker_id, date_from, date_to, sort, page, page_size
    )


@router.get("/stats")
def get_stats(
    keyword: str | None = None,
    worker_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return review_admin_controller.get_stats(db, keyword, worker_id, date_from, date_to)


@router.get("/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db)):
    return review_admin_controller.get_review(db, review_id)


@router.patch("/{review_id}/moderation")
def moderate_review(
    review_id: int,
    data: ReviewModeration,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return review_admin_controller.moderate_review(db, admin, review_id, data)
