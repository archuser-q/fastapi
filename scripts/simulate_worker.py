"""Giả lập app thợ để test app khách khi chưa có thuật toán ghép / app thợ.
"""

import sys
from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Order,
    OrderExtraQuote,
    OrderStatusHistory,
    Payment,
    Service,
    User,
    Warranty,
    WorkerProfile,
    WorkerService,
)
from app.services.notification_service import notify
from app.utils.dates import now_vn
from app.utils.security import hash_password

STATUS_TEXT = {
    "accepted": "Thợ đã nhận đơn",
    "on_the_way": "Thợ đang trên đường tới",
    "arrived": "Thợ đã tới nơi",
    "in_progress": "Thợ đang sửa chữa",
    "completed": "Đơn đã hoàn thành",
}


def _demo_worker(db, order: Order) -> int:
    u = db.scalar(select(User).where(User.phone == "0900000001"))
    if not u:
        u = User(phone="0900000001", full_name="Thợ Demo", role="worker", password_hash=hash_password("12345678"))
        db.add(u)
        db.flush()
        db.add(WorkerProfile(user_id=u.id, verification_status="approved", availability="online", experience_years=5))
        db.flush()
    p = db.get(WorkerProfile, u.id)
    # đặt thợ cách đơn ~1km
    p.current_latitude = order.latitude + 0.008
    p.current_longitude = order.longitude + 0.004
    p.location_updated_at = now_vn()
    if not db.get(WorkerService, (u.id, order.service_id)):
        db.add(WorkerService(worker_id=u.id, service_id=order.service_id))
    return u.id


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    order_id, action = int(sys.argv[1]), sys.argv[2]
    with SessionLocal() as db:
        o = db.get(Order, order_id)
        if not o:
            print("Không có đơn", order_id)
            return

        if action == "quote":
            amount, desc = int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "Vật tư phát sinh"
            db.add(OrderExtraQuote(order_id=o.id, worker_id=o.worker_id, description=desc, amount=amount))
            notify(db, o.customer_id, "Thợ gửi báo giá phát sinh", f"{desc}: {amount:,}đ", "extra_quote", o.id)
        elif action == "confirm-cash":
            p = db.scalar(select(Payment).where(Payment.order_id == o.id, Payment.status == "pending", Payment.method == "cash"))
            if not p:
                print("Không có thanh toán tiền mặt đang chờ")
                return
            p.status, p.paid_at = "success", now_vn()
            notify(db, o.customer_id, "Thợ đã xác nhận nhận tiền", f"Đơn #{o.id}", "payment", o.id)
        elif action in STATUS_TEXT:
            if o.worker_id is None:
                o.worker_id = _demo_worker(db, o)
            o.status = action
            if action == "accepted":
                o.accepted_at = now_vn()
            if action == "completed":
                o.completed_at = now_vn()
                p = db.get(WorkerProfile, o.worker_id)
                p.completed_orders += 1
                if not db.scalar(select(Warranty).where(Warranty.order_id == o.id)):
                    today = now_vn().date()
                    db.add(Warranty(order_id=o.id, terms="Bảo hành 30 ngày", start_date=today, end_date=today + timedelta(days=30)))
            elif o.status in ("on_the_way",):
                # thợ tiến gần hơn
                p = db.get(WorkerProfile, o.worker_id)
                p.current_latitude = o.latitude + 0.003
                p.current_longitude = o.longitude + 0.002
                p.location_updated_at = now_vn()
            db.add(OrderStatusHistory(order_id=o.id, status=action, changed_by=o.worker_id))
            notify(db, o.customer_id, STATUS_TEXT[action], f"Đơn #{o.id}", "order_status", o.id)
        else:
            print("Hành động không hợp lệ:", action)
            return
        db.commit()
        print(f"Đơn #{o.id}: {action} OK (worker_id={o.worker_id})")


if __name__ == "__main__":
    main()
