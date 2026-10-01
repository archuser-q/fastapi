from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.controllers import admin_controller
from app.database import get_db
from app.middleware.auth import require_roles
from app.schemas.admin import CreateStaffRequest

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.post("/staff", status_code=201)
def create_staff(data: CreateStaffRequest, db: Session = Depends(get_db)):
    return admin_controller.create_staff(db, data)