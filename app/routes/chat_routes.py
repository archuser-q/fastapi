"""Chat theo đơn — dùng chung cho khách và thợ."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import chat_controller
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.schemas.customer import MessageCreate

router = APIRouter(prefix="/orders/{order_id}/messages", tags=["Chat"])


@router.get("")
def list_messages(
    order_id: int,
    before_id: int | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return chat_controller.list_messages(db, user, order_id, before_id, limit)


@router.post("", status_code=201)
def send_message(
    order_id: int, data: MessageCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return chat_controller.send_message(db, user, order_id, data)


@router.post("/read")
def mark_read(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return chat_controller.mark_read(db, user, order_id)
