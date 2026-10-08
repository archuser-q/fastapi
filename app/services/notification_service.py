from sqlalchemy.orm import Session

from app.models import Notification


def notify(
    db: Session,
    user_id: int | None,
    title: str,
    body: str | None = None,
    type_: str | None = None,
    reference_id: int | None = None,
) -> None:
    """Thêm thông báo vào session; nơi gọi tự commit."""
    if user_id is None:
        return
    db.add(
        Notification(
            user_id=user_id, title=title, body=body, type=type_, reference_id=reference_id
        )
    )
