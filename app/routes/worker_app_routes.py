"""API dành cho app thợ."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.controllers import geo_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.geo import LocationUpdate

worker_only = require_roles("worker")

router = APIRouter(prefix="/worker", tags=["Worker App"])


@router.patch("/location")
def update_location(
    data: LocationUpdate,
    db: Session = Depends(get_db),
    worker: User = Depends(worker_only),
):
    return geo_controller.update_worker_location(db, worker, data)
