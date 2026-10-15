"""Thợ ảo (bot) — giả lập nhiều thợ dùng app để DEMO và KIỂM THỬ khi không đủ điện thoại.

Bot dùng chính nghiệp vụ của app thợ (cùng hàm với API), nên đơn đi qua đúng luồng thật:
nhận offer từ bộ điều phối -> nhận/từ chối -> di chuyển tới khách (toạ độ thay đổi dần, app khách
thấy thợ chạy trên bản đồ) -> đến nơi -> sửa -> chụp ảnh -> hoàn thành -> xác nhận tiền mặt.

    # trong Docker
    docker compose exec api python -m scripts.worker_bots --count 10
    # tham số: --accept 0.85 (xác suất nhận đơn), --speed 300 (m mỗi nhịp), --tick 2 (giây)

Chỉ điều khiển các thợ được seed sẵn (SĐT 098xxxxxxx của seed_dashboard), không đụng tài khoản thật/demo.
Ctrl+C để dừng (bot tắt nhận đơn trước khi thoát).
"""

import argparse
import math
import random
import signal
import time
from datetime import timedelta

from sqlalchemy import select

from app.controllers import worker_job_controller as jobs
from app.controllers import worker_profile_controller as profile_ctl
from app.database import SessionLocal
from app.models import Order, OrderOffer, OrderPhoto, OrderStatusHistory, Payment, User, WorkerProfile
from app.schemas.worker_app import AdvanceStatusRequest, PhotoCreate
from app.services import dispatch_service
from app.utils.dates import now_vn
from db.seed_media import seed_media_urls

HOAN_KIEM = (21.0285, 105.8542)
STOP = False


def _km(lat1, lng1, lat2, lng2):
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def _photo_url(kind: str) -> str:
    return seed_media_urls()[f"job-{kind}"]


def _last_change(db, order_id):
    return db.scalar(
        select(OrderStatusHistory.created_at)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at.desc(), OrderStatusHistory.id.desc())
        .limit(1)
    )


def _pick_bots(db, count):
    return db.scalars(
        select(User)
        .join(WorkerProfile, WorkerProfile.user_id == User.id)
        .where(
            User.role == "worker",
            User.status == "active",
            User.phone.like("098%"),
            ~User.phone.like("0987%"),  # chừa tài khoản demo 0987xxxxxx
            WorkerProfile.verification_status == "approved",
        )
        .order_by(User.id)
        .limit(count)
    ).all()


def _go_online(db, bot: User, center, radius_km):
    p = db.get(WorkerProfile, bot.id)
    if p.current_latitude is None or _km(p.current_latitude, p.current_longitude, *center) > radius_km:
        d, b = radius_km * math.sqrt(random.random()), random.uniform(0, 2 * math.pi)
        p.current_latitude = center[0] + d / 111.32 * math.cos(b)
        p.current_longitude = center[1] + d / (111.32 * math.cos(math.radians(center[0]))) * math.sin(b)
    if not bot.phone:
        bot.phone = "098" + str(bot.id).zfill(7)
    p.location_updated_at = now_vn()
    if p.availability == "offline":
        p.availability = "online"
    db.commit()


def _heartbeat(db, bot: User):
    p = db.get(WorkerProfile, bot.id)
    p.current_latitude += random.uniform(-0.0003, 0.0003)
    p.current_longitude += random.uniform(-0.0003, 0.0003)
    p.location_updated_at = now_vn()
    db.commit()


def _handle_offers(db, bot: User, accept_prob):
    offer = db.scalar(select(OrderOffer).where(OrderOffer.worker_id == bot.id, OrderOffer.status == "sent"))
    if not offer or offer.expires_at is None:
        return
    waited = (now_vn() - offer.sent_at).total_seconds()
    decide_after = 3 + (offer.id * 7) % 8  # mỗi offer "suy nghĩ" 3-10 giây
    if waited < decide_after:
        return
    try:
        if random.random() < accept_prob:
            dispatch_service.accept_offer(db, bot, offer.id)
            print(f"  [bot {bot.full_name}] NHẬN đơn #{offer.order_id}")
        else:
            dispatch_service.reject_offer(db, bot, offer.id, random.choice(["Đang bận việc khác", "Quá xa"]))
            print(f"  [bot {bot.full_name}] từ chối đơn #{offer.order_id}")
    except Exception as e:  # đơn đã có người khác nhận / khách hủy
        db.rollback()
        print(f"  [bot {bot.full_name}] bỏ qua đơn #{offer.order_id}: {getattr(e, 'detail', e)}")


def _progress_jobs(db, bot: User, step_m):
    orders = db.scalars(
        select(Order).where(Order.worker_id == bot.id, Order.status.in_(("accepted", "on_the_way", "arrived", "in_progress", "completed")))
    ).all()
    now = now_vn()
    for o in orders:
        since = (now - (_last_change(db, o.id) or now)).total_seconds()
        try:
            if o.status == "accepted" and (o.scheduled_at is None or o.scheduled_at - now < timedelta(minutes=30)) and since > 4:
                jobs.advance_status(db, bot, o.id, AdvanceStatusRequest(status="on_the_way"))
            elif o.status == "on_the_way":
                p = db.get(WorkerProfile, bot.id)
                dist = _km(p.current_latitude, p.current_longitude, o.latitude, o.longitude)
                if dist * 1000 <= step_m:
                    profile_ctl.update_location(db, bot, o.latitude, o.longitude)
                    jobs.advance_status(db, bot, o.id, AdvanceStatusRequest(status="arrived"))
                else:
                    f = step_m / (dist * 1000)
                    lat = p.current_latitude + (o.latitude - p.current_latitude) * f
                    lng = p.current_longitude + (o.longitude - p.current_longitude) * f
                    profile_ctl.update_location(db, bot, lat, lng)
            elif o.status == "arrived" and since > 8:
                jobs.add_photos(db, bot, o.id, PhotoCreate(kind="before", urls=[_photo_url("before")]))
                jobs.advance_status(db, bot, o.id, AdvanceStatusRequest(status="in_progress", safety_confirmed=True))
            elif o.status == "in_progress" and since > 15:
                if not db.scalar(select(OrderPhoto.id).where(OrderPhoto.order_id == o.id, OrderPhoto.kind == "after")):
                    jobs.add_photos(db, bot, o.id, PhotoCreate(kind="after", urls=[_photo_url("after")]))
                jobs.advance_status(db, bot, o.id, AdvanceStatusRequest(status="completed"))
                print(f"  [bot {bot.full_name}] HOÀN THÀNH đơn #{o.id}")
            elif o.status == "completed":
                pending_cash = db.scalar(
                    select(Payment.id).where(Payment.order_id == o.id, Payment.method == "cash", Payment.status == "pending")
                )
                if pending_cash:
                    jobs.confirm_cash(db, bot, o.id)
                    print(f"  [bot {bot.full_name}] đã thu tiền mặt đơn #{o.id}")
        except Exception as e:
            db.rollback()
            print(f"  [bot {bot.full_name}] đơn #{o.id}: {getattr(e, 'detail', e)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--accept", type=float, default=0.85, help="xác suất nhận đơn")
    ap.add_argument("--speed", type=float, default=250, help="mét di chuyển mỗi nhịp")
    ap.add_argument("--tick", type=float, default=2.0)
    ap.add_argument("--lat", type=float, default=HOAN_KIEM[0])
    ap.add_argument("--lng", type=float, default=HOAN_KIEM[1])
    ap.add_argument("--radius", type=float, default=3.0, help="bán kính rải bot quanh tâm (km)")
    args = ap.parse_args()

    def stop(*_):
        global STOP
        STOP = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with SessionLocal() as db:
        bots = _pick_bots(db, args.count)
        if not bots:
            print("Không có thợ seed nào (chạy python -m db.seed_dashboard trước)")
            return
        ids = [b.id for b in bots]
        for b in bots:
            _go_online(db, b, (args.lat, args.lng), args.radius)
    print(f"Đã bật {len(ids)} thợ ảo quanh ({args.lat}, {args.lng}). Ctrl+C để dừng.")

    last_beat = 0.0
    while not STOP:
        with SessionLocal() as db:
            bots = db.scalars(select(User).where(User.id.in_(ids))).all()
            beat = time.monotonic() - last_beat > 30
            for b in bots:
                if beat:
                    _heartbeat(db, b)
                _handle_offers(db, b, args.accept)
                _progress_jobs(db, b, args.speed)
            if beat:
                last_beat = time.monotonic()
        time.sleep(args.tick)

    with SessionLocal() as db:
        for wid in ids:
            p = db.get(WorkerProfile, wid)
            p.availability = "offline"
        db.commit()
    print("Đã tắt thợ ảo.")


if __name__ == "__main__":
    main()
