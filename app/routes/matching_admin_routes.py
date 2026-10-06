"""Cấu hình và công cụ kiểm tra thuật toán ghép thợ (web quản trị)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import geo_controller, matching_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.matching import MatchingConfigCreate, MatchingConfigUpdate, SimulateRequest

admin_only = require_roles("admin")

router = APIRouter(
    prefix="/admin/matching",
    tags=["Admin - Matching"],
    dependencies=[Depends(admin_only)],
)


# ---------- Cấu hình ----------


@router.get("/configs")
def list_configs(db: Session = Depends(get_db)):
    return matching_controller.list_configs(db)


@router.post("/configs")
def create_config(
    data: MatchingConfigCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return matching_controller.create_config(db, admin, data)


@router.put("/configs/{config_id}")
def update_config(
    config_id: int,
    data: MatchingConfigUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return matching_controller.update_config(db, admin, config_id, data)


@router.post("/configs/{config_id}/activate")
def activate_config(
    config_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    return matching_controller.activate_config(db, admin, config_id)


@router.delete("/configs/{config_id}")
def delete_config(config_id: int, db: Session = Depends(get_db)):
    return matching_controller.delete_config(db, config_id)


# ---------- Kiểm tra thuật toán ----------


@router.post("/simulate")
def simulate(data: SimulateRequest, db: Session = Depends(get_db)):
    return matching_controller.simulate(db, data)


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
