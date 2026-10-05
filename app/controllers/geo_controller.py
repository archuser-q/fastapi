from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User, WorkerProfile
from app.schemas.geo import LocationOut, LocationUpdate
from app.services.geo_service import find_nearby_workers
from app.utils.dates import now_vn
from app.utils.response import success


def update_worker_location(db: Session, worker: User, data: LocationUpdate):
    profile = db.get(WorkerProfile, worker.id)
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy hồ sơ thợ")

    profile.current_latitude = data.latitude
    profile.current_longitude = data.longitude
    profile.location_updated_at = now_vn()
    db.commit()
    db.refresh(profile)  # đọc lại geohash do trigger trong database tính

    return success(
        LocationOut(
            latitude=profile.current_latitude,
            longitude=profile.current_longitude,
            geohash=profile.geohash,
            location_updated_at=profile.location_updated_at,
        ),
        "Đã cập nhật vị trí",
    )


def search_nearby_workers(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float,
    service_id: int | None,
    include_busy: bool,
    max_location_age_minutes: int | None,
    limit: int,
):
    fresh_after = (
        now_vn() - timedelta(minutes=max_location_age_minutes) if max_location_age_minutes else None
    )
    workers = find_nearby_workers(
        db,
        latitude,
        longitude,
        radius_km,
        service_id=service_id,
        statuses=("online", "busy") if include_busy else ("online",),
        fresh_after=fresh_after,
        limit=limit,
    )
    return success(workers)
