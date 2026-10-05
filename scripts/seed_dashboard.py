import random
import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    Complaint,
    MatchingConfig,
    Order,
    OrderOffer,
    OrderStatusHistory,
    Payment,
    Review,
    Service,
    ServiceCategory,
    User,
    WorkerDocument,
    WorkerEarning,
    WorkerProfile,
)
from app.utils.dates import now_vn
from app.utils.security import hash_password

random.seed(42)

CATEGORIES = {
    "Điện": [("Sửa ổ cắm", 150000), ("Lắp đèn", 200000), ("Sửa aptomat", 250000)],
    "Nước": [("Sửa vòi nước", 150000), ("Thông tắc bồn cầu", 300000)],
    "Điện lạnh": [("Vệ sinh điều hòa", 250000), ("Nạp gas điều hòa", 450000), ("Sửa tủ lạnh", 400000)],
    "Đồ gia dụng": [("Sửa máy giặt", 350000), ("Sửa bình nóng lạnh", 300000)],
}
FLOW = ["matched", "accepted", "on_the_way", "arrived", "in_progress", "completed"]
LAST_NAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
FIRST_NAMES = ["An", "Bình", "Cường", "Dũng", "Hà", "Hùng", "Lan", "Minh", "Nam", "Quân", "Tâm", "Tuấn"]


def name():
    return f"{random.choice(LAST_NAMES)} Văn {random.choice(FIRST_NAMES)}"


def main():
    db = SessionLocal()
    try:
        if db.scalar(select(func.count(Order.id))):
            print("Database đã có đơn hàng, bỏ qua seed")
            sys.exit(0)

        now = now_vn()
        pw = hash_password("12345678")

        if not db.scalar(select(User).where(User.phone == "0900000000")):
            db.add(User(phone="0900000000", full_name="Quản trị viên", password_hash=pw, role="admin"))

        services = []
        for cat_name, items in CATEGORIES.items():
            cat = ServiceCategory(name=cat_name)
            db.add(cat)
            db.flush()
            for svc_name, price in items:
                svc = Service(category_id=cat.id, name=svc_name, base_price=Decimal(price))
                db.add(svc)
                services.append(svc)
        db.flush()

        customers = []
        for i in range(60):
            u = User(
                phone=f"091{i:07d}", full_name=name(), password_hash=pw, role="customer",
                created_at=now - timedelta(days=random.randint(0, 270)),
            )
            db.add(u)
            customers.append(u)

        workers = []
        for i in range(25):
            u = User(
                phone=f"098{i:07d}", full_name=name(), password_hash=pw, role="worker",
                created_at=now - timedelta(days=random.randint(0, 270)),
            )
            db.add(u)
            db.flush()
            status = "approved" if i < 20 else ("pending" if i < 24 else "rejected")
            profile = WorkerProfile(
                user_id=u.id,
                verification_status=status,
                availability=random.choice(["online", "busy", "offline"]) if status == "approved" else "offline",
                trust_score=Decimal(str(round(random.uniform(0.6, 0.98), 4))),
                created_at=u.created_at,
            )
            db.add(profile)
            db.flush()
            for doc in ("id_card_front", "id_card_back", "portrait"):
                db.add(WorkerDocument(
                    worker_id=u.id, doc_type=doc, file_url="https://example.com/doc.jpg",
                    status="approved" if status == "approved" else "pending",
                    uploaded_at=now - timedelta(days=random.randint(0, 4)),
                ))
            if status == "approved":
                workers.append(u)
        db.flush()

        db.add(MatchingConfig(
            name="Mặc định", mode="instant", weight_distance=Decimal("0.4"),
            weight_trust=Decimal("0.3"), weight_price=Decimal("0.1"),
            weight_workload=Decimal("0.2"), is_active=True,
        ))

        stats = {w.id: [0, 0] for w in workers}
        for n in range(700):
            created = now - timedelta(days=random.betavariate(1, 3) * 270, minutes=random.randint(0, 1440))
            if n < 15:
                created = now - timedelta(minutes=random.randint(5, 150))
            if created > now:
                created = now - timedelta(minutes=random.randint(1, 60))
            svc = random.choice(services)
            age_hours = (now - created).total_seconds() / 3600
            roll = random.random()
            if age_hours < 0.5 and roll < 0.5:
                final_status = "pending"
            elif roll < 0.12:
                final_status = "cancelled"
            elif age_hours < 3:
                final_status = random.choice(FLOW[:-1])
            else:
                final_status = "completed"

            worker = random.choice(workers) if final_status not in ("pending",) and roll >= 0.05 else None
            if final_status not in ("pending", "cancelled") and worker is None:
                worker = random.choice(workers)

            price = int(svc.base_price) + random.choice([0, 50000, 100000, 150000])
            order = Order(
                customer_id=random.choice(customers).id,
                worker_id=worker.id if worker else None,
                service_id=svc.id,
                address_line="Hà Nội",
                latitude=21.02 + random.uniform(-0.05, 0.05),
                longitude=105.83 + random.uniform(-0.05, 0.05),
                status=final_status,
                estimated_price=Decimal(price),
                matching_mode="instant",
                created_at=created,
            )
            db.add(order)
            db.flush()

            t = created
            history = []
            if worker:
                db.add(OrderOffer(order_id=order.id, worker_id=worker.id, status="accepted",
                                  sent_at=created, responded_at=created + timedelta(minutes=2)))
                other = random.choice(workers)
                if other.id != worker.id:
                    db.add(OrderOffer(order_id=order.id, worker_id=other.id,
                                      status=random.choice(["rejected", "expired"]), sent_at=created))
                steps = FLOW if final_status in ("completed",) else FLOW[: FLOW.index(final_status) + 1] if final_status in FLOW else FLOW[:2]
                for st in steps:
                    t += timedelta(minutes=random.randint(2, 40))
                    if t > now:
                        t = now
                    history.append((st, t))
                    if st == "accepted":
                        order.accepted_at = t
            if final_status == "cancelled":
                order.cancel_reason = "Khách hủy"
                history.append(("cancelled", min(t + timedelta(minutes=5), now)))
            for st, at in history:
                db.add(OrderStatusHistory(order_id=order.id, status=st, created_at=at,
                                          changed_by=worker.id if worker else None))

            if final_status == "completed":
                order.completed_at = t
                order.final_price = Decimal(price)
                commission = int(price * 0.15)
                db.add(WorkerEarning(worker_id=worker.id, order_id=order.id, gross_amount=price,
                                     commission_amount=commission, net_amount=price - commission,
                                     created_at=t))
                pay_status = "success" if random.random() > 0.05 else random.choice(["pending", "failed"])
                db.add(Payment(order_id=order.id, amount=price,
                               method=random.choice(["cash", "momo", "vnpay", "momo"]),
                               status=pay_status, created_at=t,
                               paid_at=t if pay_status == "success" else None))
                stats[worker.id][1] += 1
                if random.random() < 0.8:
                    rating = random.choices([5, 4, 3, 2, 1], weights=[55, 28, 10, 4, 3])[0]
                    flagged = rating <= 2 and random.random() < 0.4
                    db.add(Review(order_id=order.id, customer_id=order.customer_id, worker_id=worker.id,
                                  rating=rating, comment="", is_flagged=flagged,
                                  flag_reason="Ngôn từ không phù hợp" if flagged else None,
                                  created_at=min(t + timedelta(hours=1), now)))
                    stats[worker.id][0] += 1
                if random.random() < 0.04:
                    c_created = min(t + timedelta(hours=random.randint(1, 30)), now)
                    c_status = random.choice(["open", "processing", "resolved", "rejected"])
                    db.add(Complaint(order_id=order.id, complainant_id=order.customer_id,
                                     reason="Thợ làm chưa đạt yêu cầu", status=c_status,
                                     created_at=c_created,
                                     resolved_at=c_created + timedelta(hours=random.randint(2, 48))
                                     if c_status in ("resolved", "rejected") else None))

        for w in workers:
            profile = db.get(WorkerProfile, w.id)
            profile.review_count, profile.completed_orders = stats[w.id]

        db.commit()
        print("Đã seed dữ liệu demo. Admin: 0900000000 / 12345678")
    finally:
        db.close()


if __name__ == "__main__":
    main()
