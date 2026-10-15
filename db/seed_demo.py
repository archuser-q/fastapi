"""Tài khoản demo cho App Thợ / App Khách (chạy nhiều lần không sao).

    python -m db.seed_demo

Mật khẩu chung: 12345678
  - tho@thonhanh.vn       Thợ đã duyệt (Trần Minh Đức)
  - tho2@thonhanh.vn      Thợ đã duyệt thứ 2 (Nguyễn Văn Bình) — dùng để demo 2 thợ tranh đơn
  - tho.moi@thonhanh.vn   Thợ vừa gửi hồ sơ, chờ admin duyệt (demo màn duyệt hồ sơ ở web quản trị)
  - khach@thonhanh.vn     Khách hàng (SĐT 0912000001) có sẵn địa chỉ gần Hồ Gươm
  - admin@thonhanh.vn     Quản trị (SĐT 0900000000)
"""

from decimal import Decimal

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    CustomerAddress,
    MatchingConfig,
    Service,
    User,
    WorkerBankAccount,
    WorkerDocument,
    WorkerProfile,
    WorkerService,
)
from app.utils.dates import now_vn
from app.utils.security import hash_password
from db.seed_demo_history import seed_history
from db.seed_media import seed_media_urls, upgrade_svg_urls

PASSWORD = "12345678"
HOAN_KIEM = (21.0285, 105.8542)

def _user(db, email, phone, name, role) -> User:
    u = db.scalar(select(User).where(func.lower(User.email) == email))
    if not u and phone:
        u = db.scalar(select(User).where(User.phone == phone))
    if u is None:
        u = User(email=email, phone=phone, full_name=name, role=role, password_hash=hash_password(PASSWORD))
        db.add(u)
        db.flush()
    return u


def _worker(db, urls, email, phone, name, *, approved, lat, lng, trust, exp, bio):
    u = _user(db, email, phone, name, "worker")
    p = db.get(WorkerProfile, u.id)
    if p is None:
        p = WorkerProfile(user_id=u.id)
        db.add(p)
        db.flush()
    if db.scalar(select(func.count()).select_from(WorkerDocument).where(WorkerDocument.worker_id == u.id)):
        return u  # đã seed rồi
    now = now_vn()
    p.experience_years, p.bio, p.service_radius_km = exp, bio, Decimal("10")
    p.trust_score = Decimal(str(trust))
    p.submitted_at = now
    p.verification_status = "approved" if approved else "pending"
    p.availability = "offline"
    p.current_latitude, p.current_longitude, p.location_updated_at = lat, lng, now
    for t in ("id_card_front", "id_card_back", "portrait", "certificate"):
        db.add(
            WorkerDocument(
                worker_id=u.id,
                doc_type=t,
                file_url=urls[t],
                status="approved" if approved else "pending",
                uploaded_at=now,
                reviewed_at=now if approved else None,
            )
        )
    for sid in db.scalars(select(Service.id).where(Service.is_active.is_(True))).all():
        if not db.get(WorkerService, (u.id, sid)):
            db.add(WorkerService(worker_id=u.id, service_id=sid))
    if approved:
        db.add(
            WorkerBankAccount(
                worker_id=u.id, bank_name="Vietcombank", account_number="0011004567" + phone[-2:], account_holder=name.upper()
            )
        )
    return u


def main():
    urls = seed_media_urls()
    with SessionLocal() as db:
        if not db.scalar(select(func.count(Service.id))):
            print("[seed_demo] Chưa có danh mục dịch vụ -> chạy db.seed_dashboard trước")
            return
        if upgrade_svg_urls(db):
            db.commit()

        admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if admin and not admin.email and not db.scalar(select(User).where(User.email == "admin@thonhanh.vn")):
            admin.email = "admin@thonhanh.vn"
        if not admin:
            _user(db, "admin@thonhanh.vn", "0900000000", "Quản trị viên", "admin")

        lat, lng = HOAN_KIEM
        _worker(db, urls, "tho@thonhanh.vn", "0987000001", "Trần Minh Đức", approved=True, lat=lat + 0.006, lng=lng + 0.004,
                trust=0.92, exp=8, bio="Thợ điện dân dụng 8 năm, chuyên sửa chập điện, thay aptomat, lắp đèn.")
        _worker(db, urls, "tho2@thonhanh.vn", "0987000002", "Nguyễn Văn Bình", approved=True, lat=lat - 0.01, lng=lng + 0.008,
                trust=0.85, exp=5, bio="Lắp đặt điện nhà mới, đi dây âm tường, tủ điện.")
        _worker(db, urls, "tho.moi@thonhanh.vn", "0987000003", "Lê Quang Minh", approved=False, lat=lat + 0.012, lng=lng - 0.006,
                trust=0, exp=2, bio="Thợ mới đăng ký.")

        cus = _user(db, "khach@thonhanh.vn", "0912000001", "Nguyễn Thu Hà", "customer")
        if not db.scalar(select(CustomerAddress.id).where(CustomerAddress.customer_id == cus.id)):
            db.add(CustomerAddress(customer_id=cus.id, label="Nhà", address_line="15 Hàng Bài, Hoàn Kiếm, Hà Nội",
                                   latitude=lat - 0.004, longitude=lng + 0.002, is_default=True))
        db.commit()

        # Lịch sử làm việc để app có dữ liệu trình diễn (chỉ tạo 1 lần)
        made = []
        for email, days, per_day, seed, today in (
            ("tho@thonhanh.vn", 42, (2, 3, 3, 4), 11, 2),
            ("tho2@thonhanh.vn", 28, (1, 2, 2, 3), 22, 1),
        ):
            w = db.scalar(select(User).where(func.lower(User.email) == email))
            n = seed_history(db, w, days=days, jobs_per_day=per_day, seed=seed, today_jobs=today) if w else 0
            if n:
                made.append(f"{email}: {n} đơn")
        db.commit()
        if made:
            print("[seed_demo] Lịch sử demo:", ", ".join(made))
        moved = _refresh_demo_appointments(db)
        if moved:
            print(f"[seed_demo] Dời {moved} lịch hẹn mẫu đã quá giờ sang sáng ngày làm việc kế tiếp")
        if _ensure_auto_config(db):
            print("[seed_demo] Bật cấu hình ghép 'Tự động (hybrid)' — admin đổi lại được ở web quản trị")
    print(
        "[seed_demo] Tài khoản demo (mật khẩu 12345678): tho@thonhanh.vn, tho2@thonhanh.vn, tho.moi@thonhanh.vn, "
        "khach@thonhanh.vn (SĐT 0912000001), admin@thonhanh.vn (SĐT 0900000000)"
    )


def _refresh_demo_appointments(db) -> int:
    """Lịch hẹn mẫu (seed) là "sáng mai 9:30" tính từ ngày seed; vài hôm sau nó thành quá giờ mà vẫn "đã nhận"
    -> thợ demo bị tính là bận và không nhận được đơn mới. Mỗi lần khởi động, dời các lịch mẫu đã quá giờ
    (chưa bắt đầu đi) sang 9:30 sáng ngày làm việc kế tiếp. Chỉ đụng tới đơn do seed tạo (nhận theo mô tả cố định)."""
    from datetime import datetime, time, timedelta

    from app.models import Order
    from app.services import worker_service as ws
    from db.seed_demo_history import DEMO_APPOINTMENT_DESC

    now = now_vn()
    nxt = now.date() + timedelta(days=1)
    if nxt.weekday() == 6:
        nxt += timedelta(days=1)
    start = datetime.combine(nxt, time(9, 30))
    stale = db.scalars(
        select(Order).where(
            Order.description == DEMO_APPOINTMENT_DESC,
            Order.status == "accepted",
            Order.scheduled_at.is_not(None),
            Order.scheduled_at < now,
        )
    ).all()
    for o in stale:
        o.scheduled_at = start
        ws.refresh_availability(db, o.worker_id)
    db.commit()
    return len(stale)


AUTO_CONFIG_NAME = "Tự động (hybrid)"


def _ensure_auto_config(db) -> bool:
    """Tạo 1 lần cấu hình ghép chế độ auto và đặt làm cấu hình đang áp dụng (CSDL cũ cũng được nâng cấp 1 lần).
    Sau đó admin đổi cấu hình nào thì giữ nguyên lựa chọn của admin."""
    if db.scalar(select(MatchingConfig.id).where(MatchingConfig.mode == "auto")):
        return False
    base = db.scalar(select(MatchingConfig).where(MatchingConfig.is_active.is_(True)))
    for c in db.scalars(select(MatchingConfig).where(MatchingConfig.is_active.is_(True))):
        c.is_active = False
    db.flush()  # tắt cấu hình cũ trước khi thêm cấu hình mới (chỉ 1 cấu hình được áp dụng)
    db.add(
        MatchingConfig(
            name=AUTO_CONFIG_NAME,
            mode="auto",
            weight_distance=base.weight_distance if base else Decimal("0.4"),
            weight_trust=base.weight_trust if base else Decimal("0.3"),
            weight_price=base.weight_price if base else Decimal("0.1"),
            weight_workload=base.weight_workload if base else Decimal("0.2"),
            search_radius_km=base.search_radius_km if base else Decimal("5"),
            max_offers=base.max_offers if base else 3,
            offer_timeout_seconds=base.offer_timeout_seconds if base else 60,
            is_active=True,
        )
    )
    db.commit()
    return True


if __name__ == "__main__":
    main()
