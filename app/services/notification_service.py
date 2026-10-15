import logging
import threading

import httpx
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DeviceToken, Notification

log = logging.getLogger("thonhanh.push")
_PUSH_KEY = "pending_push"


def notify(
    db: Session,
    user_id: int | None,
    title: str,
    body: str | None = None,
    type_: str | None = None,
    reference_id: int | None = None,
) -> None:
    """Thêm thông báo vào session; nơi gọi tự commit.

    Nếu bật PUSH_ENABLED: sau khi giao dịch commit thành công, gửi thêm thông báo đẩy (Expo Push)
    tới các máy của người nhận. Giao dịch bị rollback thì không gửi gì.
    """
    if user_id is None:
        return
    db.add(
        Notification(
            user_id=user_id, title=title, body=body, type=type_, reference_id=reference_id
        )
    )
    if settings.push_enabled:
        db.info.setdefault(_PUSH_KEY, []).append(
            {"user_id": user_id, "title": title, "body": body or "", "data": {"type": type_, "reference_id": reference_id}}
        )


# ---------- Thông báo đẩy qua Expo Push Service (miễn phí, không cần khóa) ----------


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    items = session.info.pop(_PUSH_KEY, None)
    if items:
        threading.Thread(target=_send_push, args=(items,), daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_PUSH_KEY, None)


def _send_push(items: list[dict]) -> None:
    from app.database import SessionLocal  # tránh import vòng

    try:
        with SessionLocal() as db:
            user_ids = {i["user_id"] for i in items}
            rows = db.execute(
                select(DeviceToken.user_id, DeviceToken.token).where(DeviceToken.user_id.in_(user_ids))
            ).all()
        tokens: dict[int, list[str]] = {}
        for uid, tok in rows:
            if tok.startswith(("ExponentPushToken[", "ExpoPushToken[")):
                tokens.setdefault(uid, []).append(tok)
        messages = [
            {
                "to": tok,
                "title": i["title"],
                "body": i["body"],
                "data": i["data"],
                "sound": "default",
                "priority": "high",
                "channelId": "offers" if i["data"].get("type") == "offer" else "default",
            }
            for i in items
            for tok in tokens.get(i["user_id"], [])
        ]
        for start in range(0, len(messages), 100):  # Expo nhận tối đa 100 tin / lần
            httpx.post(settings.expo_push_url, json=messages[start : start + 100], timeout=10)
    except Exception:
        log.exception("Gửi thông báo đẩy thất bại")
