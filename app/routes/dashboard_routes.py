from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import dashboard_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.schemas.dashboard import Period

router = APIRouter(
    prefix="/admin/dashboard",
    tags=["Admin Dashboard - Quick View"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.get("/quick-view")
def get_quick_view(period: Period = "today", db: Session = Depends(get_db)):
    return dashboard_controller.get_quick_view(db, period)


@router.get("/summary")
def get_system_summary(db: Session = Depends(get_db)):
    return dashboard_controller.get_system_summary(db)


@router.get("/pending-tasks")
def get_pending_tasks(db: Session = Depends(get_db)):
    return dashboard_controller.get_pending_tasks(db)


@router.get("/kpis")
def get_kpis(period: Period = "today", db: Session = Depends(get_db)):
    return dashboard_controller.get_kpis(db, period)


@router.get("/orders-by-hour")
def get_orders_by_hour(
    target_date: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
):
    return dashboard_controller.get_orders_by_hour(db, target_date)
