"""Lịch sử làm việc cho thợ demo — để app thợ có dữ liệu thật mà trình diễn (thu nhập, đánh giá, ví, lịch hẹn...).

Gọi từ db.seed_demo. Chạy nhiều lần không sao: thợ đã có đơn hoàn thành thì bỏ qua.
Mọi số liệu tiền bạc đi qua đúng hàm nghiệp vụ (worker_service.record_paid_order) nên khớp với
cách hệ thống thật ghi thu nhập & ví. Thời gian tính lùi từ thời điểm chạy seed.
"""

import random
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Notification,
    Order,
    OrderExtraQuote,
    OrderOffer,
    OrderPhoto,
    OrderStatusHistory,
    Payment,
    Review,
    Service,
    User,
    WalletTransaction,
    Warranty,
    WorkerBankAccount,
    WorkerProfile,
    WorkerWithdrawal,
)
from app.services import worker_service as ws
from app.utils.dates import now_vn
from db.seed_media import seed_media_urls

# Mô tả cố định của lịch hẹn mẫu (seed_demo dùng để nhận ra và dời lịch khi đã quá giờ)
DEMO_APPOINTMENT_DESC = "Lắp quạt trần phòng khách, nhà đã có sẵn móc treo và dây chờ"

# Phố trung tâm Hà Nội (toạ độ gần đúng) — địa chỉ khách trong lịch sử
STREETS = [
    ("Hàng Bài", "Hoàn Kiếm", 21.0245, 105.8520),
    ("Tràng Tiền", "Hoàn Kiếm", 21.0247, 105.8556),
    ("Hàng Gai", "Hoàn Kiếm", 21.0315, 105.8500),
    ("Hàng Bông", "Hoàn Kiếm", 21.0300, 105.8465),
    ("Hàng Bạc", "Hoàn Kiếm", 21.0340, 105.8530),
    ("Lương Văn Can", "Hoàn Kiếm", 21.0330, 105.8505),
    ("Phan Chu Trinh", "Hoàn Kiếm", 21.0215, 105.8560),
    ("Lý Thường Kiệt", "Hoàn Kiếm", 21.0240, 105.8470),
    ("Trần Hưng Đạo", "Hoàn Kiếm", 21.0205, 105.8480),
    ("Bà Triệu", "Hai Bà Trưng", 21.0185, 105.8490),
    ("Huế", "Hai Bà Trưng", 21.0130, 105.8510),
    ("Lò Đúc", "Hai Bà Trưng", 21.0135, 105.8590),
    ("Trần Khát Chân", "Hai Bà Trưng", 21.0080, 105.8580),
    ("Bạch Mai", "Hai Bà Trưng", 21.0040, 105.8500),
    ("Nguyễn Du", "Hai Bà Trưng", 21.0170, 105.8480),
    ("Lê Duẩn", "Đống Đa", 21.0180, 105.8410),
    ("Khâm Thiên", "Đống Đa", 21.0175, 105.8370),
    ("Xã Đàn", "Đống Đa", 21.0130, 105.8330),
    ("Nguyễn Thái Học", "Ba Đình", 21.0285, 105.8380),
    ("Phan Đình Phùng", "Ba Đình", 21.0400, 105.8430),
    ("Quán Thánh", "Ba Đình", 21.0410, 105.8400),
    ("Đội Cấn", "Ba Đình", 21.0360, 105.8270),
    ("Kim Mã", "Ba Đình", 21.0315, 105.8230),
    ("Giảng Võ", "Ba Đình", 21.0265, 105.8240),
    ("Yên Phụ", "Tây Hồ", 21.0480, 105.8440),
    ("Thụy Khuê", "Tây Hồ", 21.0440, 105.8230),
]

DESCRIPTIONS = {
    "Sửa chập điện, mất điện": [
        "Nhà mất điện cả tầng 2, tầng 1 vẫn có điện",
        "Bật bình nóng lạnh là nhảy aptomat tổng",
        "Ổ điện bếp có mùi khét rồi mất điện",
    ],
    "Sửa ổ cắm, công tắc": ["Ổ cắm phòng khách lỏng, cắm vào chập chờn", "Công tắc đèn cầu thang không ăn"],
    "Sửa quạt điện": ["Quạt cây quay yếu, có tiếng kêu", "Quạt treo tường không quay, đèn vẫn sáng"],
    "Lắp đèn LED, đèn trang trí": ["Lắp 6 đèn LED âm trần phòng khách", "Thay đèn tuýp bằng đèn LED bán nguyệt"],
    "Lắp quạt trần": ["Lắp quạt trần 5 cánh phòng ngủ, đã có móc treo", "Tháo quạt cũ, lắp quạt trần có đèn"],
    "Đi dây điện mới": ["Đi thêm đường dây cho điều hoà phòng ngủ", "Kéo dây ra ban công lắp đèn"],
    "Lắp ổ cắm, công tắc mới": ["Thêm 2 ổ cắm đôi cạnh bàn làm việc", "Lắp công tắc 2 chiều cho cầu thang"],
    "Thay aptomat, cầu dao": ["Aptomat tổng hay nhảy, muốn thay loại tốt hơn", "Thay cầu dao cũ bằng aptomat"],
    "Lắp đặt tủ điện": ["Lắp tủ điện 8 đường cho nhà 3 tầng", "Chia lại tủ điện theo từng tầng"],
    "Kiểm tra an toàn điện": ["Nhà cũ 20 năm, muốn kiểm tra toàn bộ đường điện", "Kiểm tra điện trước khi cho thuê nhà"],
    "Chống giật, đo rò điện": ["Chạm vào máy giặt bị tê tay", "Vòi sen có cảm giác điện giật nhẹ"],
}
QUOTES = [
    ("Aptomat 2 cực 32A Panasonic", 180000),
    ("Dây điện Cadivi 2.5mm² (10m)", 120000),
    ("Ổ cắm đôi 3 chấu Panasonic", 85000),
    ("Công tắc 2 chiều", 60000),
    ("Tụ quạt 2.5µF", 50000),
    ("Đèn LED âm trần 9W (2 bộ)", 190000),
    ("Aptomat chống giật RCBO 20A", 380000),
    ("Ống luồn dây 20mm (5 cây)", 110000),
    ("Công đục tường đi dây âm (2m)", 200000),
]
REVIEWS = {
    5: [
        "Thợ đến đúng giờ, làm nhanh và sạch sẽ.",
        "Anh tư vấn kỹ, báo giá rõ ràng trước khi làm.",
        "Sửa xong còn kiểm tra lại các ổ cắm khác giúp nhà mình, rất có tâm.",
        "Gọi buổi tối mà vẫn có thợ tới ngay, quá ổn.",
        "Làm gọn gàng, dọn dẹp sạch sau khi sửa.",
        "Giá hợp lý, lần sau sẽ gọi lại.",
        "Giải thích rõ nguyên nhân chập điện, dặn cách dùng an toàn.",
        "Đi dây gọn, đẹp, không đục phá nhiều.",
        "Lắp quạt chắc chắn, chạy êm.",
        None,
        None,
    ],
    4: [
        "Làm ổn nhưng đến muộn khoảng 15 phút.",
        "Sửa được, giá hơi cao hơn mình nghĩ một chút.",
        "Thợ làm tốt, chỉ phải chờ đi mua thêm vật tư.",
        None,
    ],
    3: ["Lần đầu sửa chưa hết, thợ phải quay lại kiểm tra.", "Tạm được."],
}
SERVICE_WEIGHTS = {
    "Sửa chập điện, mất điện": 9,
    "Sửa ổ cắm, công tắc": 8,
    "Sửa quạt điện": 5,
    "Lắp đèn LED, đèn trang trí": 7,
    "Lắp quạt trần": 4,
    "Đi dây điện mới": 3,
    "Lắp ổ cắm, công tắc mới": 6,
    "Thay aptomat, cầu dao": 8,
    "Lắp đặt tủ điện": 1,
    "Kiểm tra an toàn điện": 3,
    "Chống giật, đo rò điện": 3,
}


def _photo_urls() -> dict[str, str]:
    """Ảnh minh hoạ trước/sau (PNG) cho vài đơn gần đây."""
    urls = seed_media_urls()
    return {"before": urls["job-before"], "after": urls["job-after"]}


def _address(rng: random.Random, near: tuple[float, float], max_km: float) -> tuple[str, float, float]:
    candidates = [s for s in STREETS if abs(s[2] - near[0]) * 111 + abs(s[3] - near[1]) * 104 <= max_km * 1.4] or STREETS
    street, district, lat, lng = rng.choice(candidates)
    return (
        f"Số {rng.randint(2, 160)} {street}, {district}, Hà Nội",
        lat + rng.uniform(-0.0015, 0.0015),
        lng + rng.uniform(-0.0015, 0.0015),
    )


def _bank_tail(db: Session, worker_id: int) -> tuple[WorkerBankAccount | None, str]:
    bank = db.get(WorkerBankAccount, worker_id)
    return bank, (bank.account_number[-4:] if bank else "0000")


def seed_history(db: Session, worker: User, *, days: int, jobs_per_day: tuple[int, ...], seed: int, today_jobs: int = 2) -> int:
    """Tạo lịch sử ~`days` ngày cho 1 thợ. Trả về số đơn hoàn thành đã tạo (0 nếu đã có lịch sử)."""
    profile = db.get(WorkerProfile, worker.id)
    if profile is None or profile.verification_status != "approved":
        return 0
    if db.scalar(select(func.count()).select_from(Order).where(Order.worker_id == worker.id, Order.status == "completed")):
        return 0

    rng = random.Random(seed)
    now = now_vn()
    base = (profile.current_latitude or 21.0285, profile.current_longitude or 105.8542)
    services = {s.name: s for s in db.scalars(select(Service).where(Service.is_active.is_(True))).all()}
    names = [n for n in SERVICE_WEIGHTS if n in services] or list(services)
    weights = [SERVICE_WEIGHTS.get(n, 1) for n in names]
    customers = db.scalars(select(User).where(User.role == "customer", User.status == "active").order_by(User.id)).all()
    if not customers or not names:
        return 0
    others = db.scalars(
        select(Order.id).where(Order.worker_id.is_not(None), Order.worker_id != worker.id, Order.created_at >= now - timedelta(days=days))
    ).all()
    rng.shuffle(others)
    photos = _photo_urls()
    bank, tail = _bank_tail(db, worker.id)
    completed: list[Order] = []
    reviews = 0

    def history(order: Order, steps: list[tuple[str, datetime]]):
        for st, at in steps:
            db.add(OrderStatusHistory(order_id=order.id, status=st, created_at=at, changed_by=worker.id if st != "pending" else order.customer_id))

    day0 = (now - timedelta(days=days)).date()
    for i in range(days + 1):
        day = day0 + timedelta(days=i)
        is_today = day == now.date()
        if day.weekday() == 6 and not is_today:  # Chủ nhật nghỉ -> chốt tuần, rút tiền
            db.flush()
            balance = ws.wallet_balance(db, worker.id)
            if bank and balance >= 600_000:
                amount = (balance - 200_000) // 50_000 * 50_000
                at = datetime.combine(day, time(20, rng.randint(0, 50)))
                w = WorkerWithdrawal(
                    worker_id=worker.id, amount=amount, bank_name=bank.bank_name, account_number=bank.account_number,
                    account_holder=bank.account_holder, status="completed", created_at=at, processed_at=at,
                    transaction_code=f"SANDBOX-WD-{uuid.UUID(int=rng.getrandbits(128)).hex[:10].upper()}",
                )
                db.add(w)
                db.flush()
                db.add(WalletTransaction(worker_id=worker.id, type="withdrawal", amount=-amount, withdrawal_id=w.id,
                                         description=f"Rút tiền về {bank.bank_name} ****{tail}", created_at=at))
            elif balance < -250_000:
                at = datetime.combine(day, time(19, rng.randint(0, 50)))
                db.add(WalletTransaction(worker_id=worker.id, type="topup", amount=300_000,
                                         description="Nạp tiền vào ví qua MoMo (sandbox)", created_at=at))
            continue

        n = today_jobs if is_today else rng.choice(jobs_per_day)
        # Khung giờ bắt đầu các việc trong ngày
        starts = sorted(rng.sample(range(8 * 60, 20 * 60, 100), n)) if n else []
        if is_today:
            latest = now.hour * 60 + now.minute - 150
            starts = [m for m in [latest - 170, latest] if m >= 7 * 60 + 30][:n]
        for m in starts:
            start = datetime.combine(day, time(m // 60, m % 60))
            svc = services[rng.choices(names, weights)[0]]
            addr, lat, lng = _address(rng, base, 3.5)
            customer = rng.choice(customers)
            scheduled = rng.random() < 0.18
            created = start - (timedelta(hours=rng.randint(5, 30)) if scheduled else timedelta(minutes=rng.randint(12, 35)))
            accepted = created + timedelta(seconds=rng.randint(20, 75))
            on_way = (start - timedelta(minutes=rng.randint(15, 30))) if scheduled else accepted + timedelta(minutes=rng.randint(2, 6))
            arrived = on_way + timedelta(minutes=rng.randint(8, 24))
            working = arrived + timedelta(minutes=rng.randint(3, 10))
            done = working + timedelta(minutes=rng.randint(25, 95))
            if done >= now:
                continue
            base_price = int(svc.base_price)
            qty = 1 if svc.unit in ("lần", "tủ") else rng.choice([1, 1, 2, 3])
            o = Order(
                customer_id=customer.id, worker_id=worker.id, service_id=svc.id, address_line=addr, latitude=lat, longitude=lng,
                description=rng.choice(DESCRIPTIONS.get(svc.name, ["Cần thợ điện kiểm tra"])),
                scheduled_at=start if scheduled else None, matching_mode="instant", status="completed",
                estimated_price=Decimal(base_price * qty), created_at=created, accepted_at=accepted, completed_at=done,
                safety_checked_at=working,
            )
            db.add(o)
            db.flush()
            db.add(OrderOffer(order_id=o.id, worker_id=worker.id, match_score=Decimal(str(round(rng.uniform(0.72, 0.95), 5))),
                              distance_km=Decimal(str(round(rng.uniform(0.4, 3.2), 3))), status="accepted", sent_at=created,
                              responded_at=accepted, expires_at=created + timedelta(seconds=60), round=1, mode="instant"))
            history(o, [("pending", created), ("accepted", accepted), ("on_the_way", on_way), ("arrived", arrived),
                        ("in_progress", working), ("completed", done)])
            total = base_price * qty
            if rng.random() < 0.3:
                desc, amount = rng.choice(QUOTES)
                db.add(OrderExtraQuote(order_id=o.id, worker_id=worker.id, description=desc, amount=Decimal(amount), status="approved",
                                       created_at=working + timedelta(minutes=8), responded_at=working + timedelta(minutes=10)))
                total += amount
            o.final_price = Decimal(total)
            method = rng.choices(["cash", "momo", "vnpay"], [55, 30, 15])[0]
            pay = Payment(order_id=o.id, amount=Decimal(total), method=method, status="success", created_at=done + timedelta(minutes=2),
                          paid_at=done + timedelta(minutes=rng.randint(2, 9)),
                          transaction_code=None if method == "cash" else f"SANDBOX-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}")
            db.add(pay)
            db.flush()
            ws.record_paid_order(db, o, pay)
            db.add(Warranty(order_id=o.id, terms=f'Bảo hành {settings.warranty_days} ngày cho hạng mục "{svc.name}" đã sửa',
                            start_date=done.date(), end_date=done.date() + timedelta(days=settings.warranty_days),
                            status="active" if done.date() + timedelta(days=settings.warranty_days) >= now.date() else "expired"))
            if (now - done).days <= 10:
                db.add(OrderPhoto(order_id=o.id, uploader_id=worker.id, kind="before", url=photos["before"], created_at=working))
                db.add(OrderPhoto(order_id=o.id, uploader_id=worker.id, kind="after", url=photos["after"], created_at=done))
            if rng.random() < 0.86:
                rating = rng.choices([5, 4, 3], [80, 17, 3])[0]
                at = min(done + timedelta(minutes=rng.randint(20, 900)), now - timedelta(minutes=5))
                db.add(Review(order_id=o.id, customer_id=customer.id, worker_id=worker.id, rating=rating,
                              comment=rng.choice(REVIEWS[rating]), created_at=at))
                reviews += 1
            completed.append(o)

        # Vài lời mời đã bỏ qua / hết hạn trong ngày (để tỷ lệ nhận đơn giống thật)
        for _ in range(rng.choice([0, 0, 0, 1])):
            if not others:
                break
            oid = others.pop()
            at = datetime.combine(day, time(rng.randint(8, 20), rng.randint(0, 59)))
            if at >= now:
                continue
            db.add(OrderOffer(order_id=oid, worker_id=worker.id, match_score=Decimal(str(round(rng.uniform(0.6, 0.85), 5))),
                              distance_km=Decimal(str(round(rng.uniform(1.0, 4.5), 3))),
                              status=rng.choice(["rejected", "expired"]), sent_at=at, responded_at=at + timedelta(seconds=40),
                              expires_at=at + timedelta(seconds=60), round=1, mode="instant",
                              reason=rng.choice(["Đang bận việc khác", "Quá xa", None])))

    # Lịch hẹn sắp tới: sáng ngày làm việc kế tiếp
    nxt = now.date() + timedelta(days=1)
    if nxt.weekday() == 6:
        nxt += timedelta(days=1)
    start = datetime.combine(nxt, time(9, 30))
    svc = services.get("Lắp quạt trần") or services[names[0]]
    addr, lat, lng = _address(rng, base, 2.5)
    customer = rng.choice(customers)
    up = Order(customer_id=customer.id, worker_id=worker.id, service_id=svc.id, address_line=addr, latitude=lat, longitude=lng,
               description=DEMO_APPOINTMENT_DESC, scheduled_at=start,
               matching_mode="instant", status="accepted", estimated_price=svc.base_price,
               created_at=now - timedelta(hours=3), accepted_at=now - timedelta(hours=3) + timedelta(seconds=40))
    db.add(up)
    db.flush()
    db.add(OrderOffer(order_id=up.id, worker_id=worker.id, match_score=Decimal("0.88123"), distance_km=Decimal("1.640"), status="accepted",
                      sent_at=up.created_at, responded_at=up.accepted_at, expires_at=up.created_at + timedelta(seconds=60), round=1, mode="instant"))
    history(up, [("pending", up.created_at), ("accepted", up.accepted_at)])

    profile.completed_orders = (profile.completed_orders or 0) + len(completed)
    profile.review_count = (profile.review_count or 0) + reviews

    # Thông báo gần đây (đã đọc phần lớn)
    recent = sorted(completed, key=lambda o: o.completed_at)[-4:]
    notes = [(f"Lịch hẹn mới: {svc.name}", f"Hẹn {start.strftime('%H:%M %d/%m')} tại {addr}", "order_status", up.id, up.created_at, False)]
    for o in recent:
        notes.append(("Khách đã thanh toán", f"Đơn {ws.order_code(o.id)}: {ws.money(int(o.final_price))}", "payment", o.id,
                      o.completed_at + timedelta(minutes=8), True))
    last_review = db.scalar(select(Review).where(Review.worker_id == worker.id).order_by(Review.created_at.desc()).limit(1))
    if last_review:
        notes.append((f"Bạn nhận được đánh giá {last_review.rating} sao", last_review.comment, "review", last_review.order_id,
                      last_review.created_at, False))
    for title, body, typ, ref, at, read in notes:
        db.add(Notification(user_id=worker.id, title=title, body=body, type=typ, reference_id=ref, is_read=read, created_at=at))
    db.flush()
    return len(completed)
