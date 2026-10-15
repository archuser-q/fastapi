"""Khách hàng giả lập — đóng vai khách để DEMO / KIỂM THỬ app thợ khi chưa có (hoặc không muốn mở) app khách.

Mọi thao tác gọi đúng nghiệp vụ của API khách (cùng hàm controller), nên đơn đi qua luồng thật:
tạo đơn -> bộ điều phối ghép thợ -> app thợ nhận offer ...

    # trong Docker (thêm "docker compose exec api" phía trước)
    python -m scripts.demo_customer order                     # đơn đặt ngay, cách thợ demo ~700 m
    python -m scripts.demo_customer order --near tho2@thonhanh.vn --dist 1500
    python -m scripts.demo_customer order --after 90          # đặt lịch hẹn sau 90 phút
    python -m scripts.demo_customer quote 12                  # duyệt báo giá phát sinh đang chờ của đơn #12
    python -m scripts.demo_customer quote 12 --reject
    python -m scripts.demo_customer pay 12 --method cash      # khách chọn trả tiền mặt (thợ bấm "Đã thu tiền")
    python -m scripts.demo_customer pay 12 --method momo      # thanh toán online sandbox -> cộng ví thợ
    python -m scripts.demo_customer review 12 --stars 5 --comment "Thợ làm nhanh, sạch sẽ"
    python -m scripts.demo_customer cancel 12
    python -m scripts.demo_customer show 12
    python -m scripts.demo_customer rush --count 12           # nhiều đơn cùng lúc (demo ghép theo lô / thợ ảo)

Mặc định đóng vai khach@thonhanh.vn (tài khoản demo); "rush" rải đơn cho nhiều khách seed sẵn.
"""

import argparse
import math
import random
import sys
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.controllers import customer_order_controller as orders
from app.controllers import customer_payment_controller as payments
from app.controllers import customer_support_controller as support
from app.database import SessionLocal
from app.models import (
    Order,
    OrderDispatch,
    OrderExtraQuote,
    OrderOffer,
    Payment,
    Service,
    User,
    WorkerProfile,
    WorkerService,
)
from app.schemas.customer import CancelRequest, OrderCreate, PaymentCreate, ReviewCreate
from app.utils.dates import now_vn
from db.seed_demo_history import DESCRIPTIONS as SERVICE_DESCRIPTIONS

HOAN_KIEM = (21.0285, 105.8542)
DEMO_CUSTOMER = "khach@thonhanh.vn"
DESCRIPTIONS = [
    "Nhà bị nhảy aptomat liên tục khi bật bình nóng lạnh",
    "Ổ cắm phòng khách có mùi khét, không dùng được",
    "Mất điện tầng 2, tầng 1 vẫn có điện",
    "Cần lắp thêm 3 bóng đèn LED âm trần phòng ngủ",
    "Quạt trần kêu to và quay yếu",
    "Công tắc cầu thang chập chờn",
]
STREETS = ["Hàng Bài", "Tràng Tiền", "Lý Thường Kiệt", "Bà Triệu", "Hàng Gai", "Đinh Tiên Hoàng", "Phan Chu Trinh"]


def _offset(lat: float, lng: float, dist_m: float) -> tuple[float, float]:
    """Điểm cách (lat, lng) khoảng dist_m mét theo một hướng ngẫu nhiên."""
    bearing = random.uniform(0, 2 * math.pi)
    dlat = dist_m * math.cos(bearing) / 111_320
    dlng = dist_m * math.sin(bearing) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def _user(db, email: str, role: str | None = None) -> User:
    u = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if not u or (role and u.role != role):
        sys.exit(f"Không tìm thấy tài khoản {role or ''} {email} (chạy python -m db.seed_demo trước)")
    return u


def _order(db, order_id: int) -> Order:
    o = db.get(Order, order_id)
    if not o:
        sys.exit(f"Không có đơn #{order_id}")
    return o


def _customer_of(db, order_id: int) -> User:
    return db.get(User, _order(db, order_id).customer_id)


def _money(n) -> str:
    return f"{int(n or 0):,}đ".replace(",", ".")


def _run(fn, *args):
    try:
        res = fn(*args)
    except HTTPException as e:
        sys.exit(f"Lỗi: {e.detail}")
    print(res.get("message", "OK") if isinstance(res, dict) else "OK")
    return res


MODE_LABEL = {"instant": "tức thời", "batch": "theo lô (Hungarian)", "auto": "tự động (hybrid)"}


# ---------- Lệnh ----------


def cmd_order(args):
    with SessionLocal() as db:
        customer = _user(db, args.customer, "customer")
        center, service_id = HOAN_KIEM, args.service
        if args.near:
            worker = _user(db, args.near, "worker")
            p = db.get(WorkerProfile, worker.id)
            if p and p.current_latitude is not None:
                center = (p.current_latitude, p.current_longitude)
            else:
                print(f"! {args.near} chưa có vị trí (chưa mở app / chưa bật nhận đơn) -> đặt quanh Hồ Gươm")
            if service_id is None:
                ids = db.scalars(select(WorkerService.service_id).where(WorkerService.worker_id == worker.id)).all()
                service_id = random.choice(ids) if ids else None
        if service_id is None:
            service_id = db.scalar(select(Service.id).where(Service.is_active.is_(True)).order_by(Service.id))
        lat, lng = _offset(*center, args.dist)
        scheduled = (now_vn() + timedelta(minutes=args.after)).replace(second=0, microsecond=0) if args.after else None
        data = OrderCreate(
            service_id=service_id,
            address_line=f"Số {random.randint(1, 120)} {random.choice(STREETS)}, Hoàn Kiếm, Hà Nội",
            latitude=lat,
            longitude=lng,
            description=args.desc or random.choice(SERVICE_DESCRIPTIONS.get(db.get(Service, service_id).name, DESCRIPTIONS)),
            scheduled_at=scheduled,
        )
        res = _run(orders.create_order, db, customer, data)
        d = res["data"]
        svc = db.get(Service, service_id)
        disp = db.get(OrderDispatch, d.id)
        cfg_mode = disp.mode if disp else db.get(Order, d.id).matching_mode
        print(
            f"  Đơn #{d.id} · {svc.name if svc else service_id} · {'hẹn ' + scheduled.strftime('%H:%M %d/%m') if scheduled else 'đặt ngay'}"
            f" · cách tâm ~{int(args.dist)} m · chế độ ghép: {MODE_LABEL.get(cfg_mode, cfg_mode)}"
        )
        # auto / theo lô: bộ điều phối (chạy trong API) gửi lời mời ở nhịp kế tiếp -> chờ tối đa vài giây để báo kết quả
        sent = []
        for _ in range(10 if cfg_mode != "instant" else 1):
            db.expire_all()
            sent = db.scalars(select(OrderOffer).where(OrderOffer.order_id == d.id, OrderOffer.status == "sent")).all()
            if sent:
                break
            time.sleep(1)
        if sent:
            names = ", ".join(db.get(User, o.worker_id).full_name for o in sent)
            how = "gửi ngay cho top-k (tức thời)" if sent[0].mode == "instant" else "ghép tối ưu Hungarian (theo lô)"
            print(f"  Đã gửi lời mời cho: {names} — {how}")
        else:
            print("  Chưa gửi lời mời (chưa có thợ phù hợp / bộ điều phối chưa chạy) — hệ thống sẽ thử lại vài giây một lần")


def cmd_quote(args):
    with SessionLocal() as db:
        customer = _customer_of(db, args.order_id)
        q = db.scalar(
            select(OrderExtraQuote)
            .where(OrderExtraQuote.order_id == args.order_id, OrderExtraQuote.status == "pending")
            .order_by(OrderExtraQuote.id.desc())
        )
        if not q:
            sys.exit(f"Đơn #{args.order_id} không có báo giá phát sinh nào đang chờ")
        print(f"  Báo giá: {q.description} — {_money(q.amount)}")
        res = _run(orders.respond_extra_quote, db, customer, args.order_id, q.id, not args.reject)
        print(f"  Tổng đơn mới: {_money(res['data']['total_amount'])}")


def cmd_pay(args):
    with SessionLocal() as db:
        customer = _customer_of(db, args.order_id)
        res = _run(payments.create_payment, db, customer, args.order_id, PaymentCreate(method=args.method))
        p = res["data"]
        print(f"  Số tiền: {_money(p.amount)} · phương thức: {args.method}")
        if args.method != "cash":
            _run(payments.sandbox_confirm, db, customer, p.id)
            print("  (sandbox) Đã cộng tiền thực nhận vào ví thợ")
        else:
            print("  Thợ sẽ thấy nút 'Đã thu tiền mặt' trong chi tiết đơn")


def cmd_review(args):
    with SessionLocal() as db:
        customer = _customer_of(db, args.order_id)
        _run(support.create_review, db, customer, args.order_id, ReviewCreate(rating=args.stars, comment=args.comment))


def cmd_cancel(args):
    with SessionLocal() as db:
        customer = _customer_of(db, args.order_id)
        _run(orders.cancel_order, db, customer, args.order_id, CancelRequest(reason=args.reason))


def cmd_show(args):
    with SessionLocal() as db:
        o = _order(db, args.order_id)
        svc = db.get(Service, o.service_id)
        w = db.get(User, o.worker_id) if o.worker_id else None
        print(f"Đơn #{o.id} · {svc.name if svc else o.service_id} · trạng thái: {o.status}")
        print(f"  Khách: {db.get(User, o.customer_id).full_name} · {o.address_line}")
        print(f"  Thợ: {w.full_name if w else '—'} · giá ước tính {_money(o.estimated_price)} · tổng {_money(orders.order_total(db, o))}")
        for off in db.scalars(select(OrderOffer).where(OrderOffer.order_id == o.id).order_by(OrderOffer.id)).all():
            score = f"{float(off.match_score):.2f}" if off.match_score is not None else "—"
            print(f"  offer #{off.id} -> {db.get(User, off.worker_id).full_name}: {off.status} (đợt {off.round}, {off.mode}, điểm {score})")
        for q in db.scalars(select(OrderExtraQuote).where(OrderExtraQuote.order_id == o.id)).all():
            print(f"  báo giá #{q.id}: {q.description} {_money(q.amount)} — {q.status}")
        for p in db.scalars(select(Payment).where(Payment.order_id == o.id)).all():
            print(f"  thanh toán #{p.id}: {p.method} {_money(p.amount)} — {p.status}")


def cmd_rush(args):
    with SessionLocal() as db:
        customers = db.scalars(select(User).where(User.role == "customer", User.status == "active").order_by(User.id)).all()
        services = db.scalars(select(Service.id).where(Service.is_active.is_(True))).all()
        if not customers or not services:
            sys.exit("Thiếu khách hàng / dịch vụ seed")
        made = 0
        names = dict(db.execute(select(Service.id, Service.name)).all())
        for i in range(args.count):
            c = customers[i % len(customers)]
            lat, lng = _offset(args.lat, args.lng, random.uniform(200, args.radius * 1000))
            sid = random.choice(services)
            data = OrderCreate(
                service_id=sid,
                address_line=f"Số {random.randint(1, 120)} {random.choice(STREETS)}, Hà Nội",
                latitude=lat,
                longitude=lng,
                description=random.choice(SERVICE_DESCRIPTIONS.get(names.get(sid, ""), DESCRIPTIONS)),
            )
            try:
                res = orders.create_order(db, c, data)
                made += 1
                print(f"  #{res['data'].id} của {c.full_name}")
            except HTTPException as e:
                db.rollback()
                print(f"  bỏ qua ({c.full_name}): {e.detail}")
        print(f"Đã tạo {made} đơn quanh ({args.lat}, {args.lng}), bán kính {args.radius} km")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("order", help="tạo 1 đơn gần 1 thợ")
    p.add_argument("--near", default="tho@thonhanh.vn", help="email thợ: đặt đơn quanh vị trí thợ này ('' = Hồ Gươm)")
    p.add_argument("--dist", type=float, default=700, help="khoảng cách tới thợ (mét)")
    p.add_argument("--service", type=int, help="id dịch vụ (mặc định: 1 dịch vụ thợ đó làm được)")
    p.add_argument("--after", type=int, default=0, help="đặt lịch hẹn sau N phút (>= 30); 0 = đặt ngay")
    p.add_argument("--desc", help="mô tả sự cố")
    p.add_argument("--customer", default=DEMO_CUSTOMER)
    p.set_defaults(fn=cmd_order)

    p = sub.add_parser("quote", help="duyệt / từ chối báo giá phát sinh đang chờ")
    p.add_argument("order_id", type=int)
    p.add_argument("--reject", action="store_true")
    p.set_defaults(fn=cmd_quote)

    p = sub.add_parser("pay", help="khách thanh toán đơn đã hoàn thành")
    p.add_argument("order_id", type=int)
    p.add_argument("--method", choices=["cash", "momo", "vnpay"], default="cash")
    p.set_defaults(fn=cmd_pay)

    p = sub.add_parser("review", help="khách đánh giá thợ")
    p.add_argument("order_id", type=int)
    p.add_argument("--stars", type=int, default=5, choices=range(1, 6))
    p.add_argument("--comment", default="Thợ đến đúng giờ, làm cẩn thận, giá hợp lý.")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("cancel", help="khách hủy đơn")
    p.add_argument("order_id", type=int)
    p.add_argument("--reason", default="Đổi kế hoạch")
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("show", help="xem trạng thái, offer, báo giá, thanh toán của đơn")
    p.add_argument("order_id", type=int)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("rush", help="tạo nhiều đơn cùng lúc")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--lat", type=float, default=HOAN_KIEM[0])
    p.add_argument("--lng", type=float, default=HOAN_KIEM[1])
    p.add_argument("--radius", type=float, default=3.0, help="km")
    p.set_defaults(fn=cmd_rush)

    args = ap.parse_args()
    if getattr(args, "after", 0) and args.after < 30:
        sys.exit("--after phải >= 30 phút (quy định đặt lịch của app khách)")
    if getattr(args, "near", None) == "":
        args.near = None
    args.fn(args)


if __name__ == "__main__":
    main()
