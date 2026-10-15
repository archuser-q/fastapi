"""Ảnh trước/sau khi sửa của 1 đơn — khách và thợ của đơn đều xem được (app khách có thể dùng để hiển thị)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models import Order, OrderPhoto, User
from app.schemas.worker_app import JobPhoto
from app.utils.response import success

router = APIRouter(prefix="/orders/{order_id}/photos", tags=["Order photos"])


@router.get("")
def list_photos(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    o = db.get(Order, order_id)
    if not o or (user.id not in (o.customer_id, o.worker_id) and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    rows = db.scalars(select(OrderPhoto).where(OrderPhoto.order_id == order_id).order_by(OrderPhoto.id)).all()
    return success([JobPhoto(id=p.id, kind=p.kind, url=p.url, created_at=p.created_at) for p in rows])
