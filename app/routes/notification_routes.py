"""Thông báo và đăng ký thiết bị nhận push — dùng chung mọi role."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import customer_account_controller, notification_controller
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.schemas.customer import DeviceTokenCreate

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return notification_controller.list_notifications(db, user, unread_only, page, page_size)


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return notification_controller.unread_count(db, user)


@router.patch("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return notification_controller.mark_all_read(db, user)


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return notification_controller.mark_read(db, user, notification_id)


@router.post("/device-tokens")
def register_device(data: DeviceTokenCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return customer_account_controller.register_device_token(db, user, data)


@router.delete("/device-tokens/{token}")
def remove_device(token: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return customer_account_controller.remove_device_token(db, user, token)
