from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Notification, User
from app.schemas.customer import NotificationOut
from app.utils.pagination import paginate
from app.utils.response import paginated, success


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        title=n.title,
        body=n.body,
        type=n.type,
        reference_id=n.reference_id,
        is_read=n.is_read,
        created_at=n.created_at,
    )


def list_notifications(db: Session, user: User, unread_only: bool, page: int, page_size: int):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows, total = paginate(db, stmt.order_by(Notification.id.desc()), page, page_size)
    return paginated([_out(n) for n in rows], total, page, page_size)


def unread_count(db: Session, user: User):
    n = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
    )
    return success({"unread": n})


def mark_read(db: Session, user: User, notification_id: int):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thông báo")
    n.is_read = True
    db.commit()
    return success(_out(n))


def mark_all_read(db: Session, user: User):
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return success({"updated": result.rowcount})
