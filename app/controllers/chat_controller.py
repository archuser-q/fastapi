from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Message, Order, User
from app.schemas.customer import MessageCreate, MessageOut
from app.services.notification_service import notify
from app.utils.response import success

CHAT_STATUSES = ("matched", "accepted", "on_the_way", "arrived", "in_progress", "completed")


def _get_order_for_participant(db: Session, user: User, order_id: int) -> Order:
    o = db.get(Order, order_id)
    if not o or user.id not in (o.customer_id, o.worker_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    return o


def _out(m: Message, me: int) -> MessageOut:
    return MessageOut(
        id=m.id,
        sender_id=m.sender_id,
        is_mine=m.sender_id == me,
        content=m.content,
        image_url=m.image_url,
        is_read=m.is_read,
        created_at=m.created_at,
    )


def list_messages(db: Session, user: User, order_id: int, before_id: int | None, limit: int):
    _get_order_for_participant(db, user, order_id)
    stmt = select(Message).where(Message.order_id == order_id)
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = db.scalars(stmt.order_by(Message.id.desc()).limit(limit)).all()
    rows.reverse()  # trả về cũ -> mới để app hiển thị thẳng
    return success([_out(m, user.id) for m in rows])


def send_message(db: Session, user: User, order_id: int, data: MessageCreate):
    o = _get_order_for_participant(db, user, order_id)
    if o.worker_id is None or o.status not in CHAT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đơn chưa có thợ hoặc đã đóng chat")

    m = Message(order_id=o.id, sender_id=user.id, content=data.content, image_url=data.image_url)
    db.add(m)
    receiver = o.worker_id if user.id == o.customer_id else o.customer_id
    preview = data.content[:80] if data.content else "[Hình ảnh]"
    notify(db, receiver, f"Tin nhắn mới - đơn #{o.id}", preview, "chat", o.id)
    db.commit()
    db.refresh(m)
    return success(_out(m, user.id))


def mark_read(db: Session, user: User, order_id: int):
    _get_order_for_participant(db, user, order_id)
    result = db.execute(
        update(Message)
        .where(Message.order_id == order_id, Message.sender_id != user.id, Message.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return success({"updated": result.rowcount})
