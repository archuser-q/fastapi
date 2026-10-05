"""Công cụ cho quản trị viên kiểm tra bước lọc thợ theo vị trí."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import geo_controller
from app.database import get_db
from app.middleware.auth import require_roles

router = APIRouter(
    prefix="/admin/matching",
    tags=["Admin - Matching"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.get("/nearby-workers")
def nearby_workers(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(5, gt=0, le=50),
    service_id: int | None = None,
    include_busy: bool = False,
    max_location_age_minutes: int | None = Query(None, ge=1, le=1440),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return geo_controller.search_nearby_workers(
        db,
        latitude,
        longitude,
        radius_km,
        service_id,
        include_busy,
        max_location_age_minutes,
        limit,
    )
