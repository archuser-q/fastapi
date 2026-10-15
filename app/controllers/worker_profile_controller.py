"""App thợ: hồ sơ, kỹ năng, giấy tờ xác minh, lịch làm việc, ngân hàng, bật/tắt nhận đơn, vị trí, trang chủ."""

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Notification,
    Order,
    OrderOffer,
    Review,
    Service,
    ServiceCategory,
    User,
    WorkerBankAccount,
    WorkerDocument,
    WorkerEarning,
    WorkerLocationLog,
    WorkerProfile,
    WorkerService,
)
from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut
from app.schemas.worker_app import (
    GeoPoint,
    WorkerLevel,
    AppSettings,
    AvailabilityOut,
    AvailabilityUpdate,
    BankAccountIn,
    BankAccountOut,
    HomeOut,
    OnboardingStatus,
    TodayStats,
    WorkerDocumentCreate,
    WorkerMe,
    WorkerProfileData,
    WorkerProfileUpdate,
    WorkerSkill,
    WorkerSkillsUpdate,
)
from app.services import dispatch_service
from app.services import worker_service as ws
from app.services.matching_service import load_active_config
from app.services.notification_service import notify
from app.utils.dates import day_start, now_vn
from app.utils.response import success

REQUIRED_DOCS = ("id_card_front", "id_card_back", "portrait")
DOC_LABEL = {
    "id_card_front": "CCCD mặt trước",
    "id_card_back": "CCCD mặt sau",
    "portrait": "Ảnh chân dung",
    "certificate": "Chứng chỉ nghề điện",
}
MAX_CERTIFICATES = 5
LOCATION_LOG_EVERY_SECONDS = 20


# ---------- Dùng chung ----------


def get_profile(db: Session, user: User, for_update: bool = False) -> WorkerProfile:
    profile = db.get(WorkerProfile, user.id, with_for_update=for_update)
    if profile is None:  # tài khoản thợ tạo trước khi có hồ sơ: tạo bù
        profile = WorkerProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        profile = db.get(WorkerProfile, user.id, with_for_update=for_update)
    return profile


def rating_avg(db: Session, worker_id: int) -> float | None:
    avg = db.scalar(
        select(func.avg(Review.rating)).where(Review.worker_id == worker_id, Review.is_hidden.is_(False))
    )
    return round(float(avg), 2) if avg is not None else None


def _skills(db: Session, worker_id: int) -> list[WorkerSkill]:
    rows = db.execute(
        select(Service, ServiceCategory.name)
        .join(WorkerService, WorkerService.service_id == Service.id)
        .join(ServiceCategory, ServiceCategory.id == Service.category_id)
        .where(WorkerService.worker_id == worker_id)
        .order_by(ServiceCategory.name, Service.name)
    ).all()
    return [
        WorkerSkill(
            service_id=s.id,
            name=s.name,
            category_id=s.category_id,
            category_name=cname,
            base_price=int(s.base_price),
            unit=s.unit,
        )
        for s, cname in rows
    ]


def _documents(db: Session, worker_id: int) -> list[WorkerDocument]:
    return db.scalars(
        select(WorkerDocument)
        .where(WorkerDocument.worker_id == worker_id)
        .order_by(WorkerDocument.uploaded_at.desc(), WorkerDocument.id.desc())
    ).all()


def _bank(db: Session, worker_id: int) -> BankAccountOut | None:
    b = db.get(WorkerBankAccount, worker_id)
    if not b:
        return None
    return BankAccountOut(
        bank_name=b.bank_name, account_number=b.account_number, account_holder=b.account_holder, updated_at=b.updated_at
    )


def _onboarding(user: User, profile: WorkerProfile, skills_count: int, docs: list[WorkerDocument]) -> OnboardingStatus:
    latest: dict[str, WorkerDocument] = {}
    usable: set[str] = set()
    for d in docs:  # docs đã sắp mới -> cũ
        latest.setdefault(d.doc_type, d)
        if d.status in ("pending", "approved"):
            usable.add(d.doc_type)

    missing, reasons = [], []
    if not user.phone:
        missing.append("Thêm số điện thoại liên hệ")
    if skills_count == 0:
        missing.append("Chọn ít nhất 1 dịch vụ nhận làm")
    for t in REQUIRED_DOCS:
        if t not in usable:
            d = latest.get(t)
            label = DOC_LABEL[t] if DOC_LABEL[t].startswith("CCCD") else DOC_LABEL[t][0].lower() + DOC_LABEL[t][1:]
            missing.append(f"{'Tải lại' if d and d.status == 'rejected' else 'Tải lên'} {label}")
    for d in latest.values():
        if d.status == "rejected" and d.reject_reason:
            reasons.append(f"{DOC_LABEL.get(d.doc_type, d.doc_type)}: {d.reject_reason}")

    can_submit = (
        not missing
        and profile.verification_status != "approved"
        and (profile.submitted_at is None or profile.verification_status == "rejected")
    )
    return OnboardingStatus(
        verification_status=profile.verification_status,
        submitted_at=profile.submitted_at,
        has_phone=bool(user.phone),
        has_skills=skills_count > 0,
        documents={t: (latest[t].status if t in latest else None) for t in (*REQUIRED_DOCS, "certificate")},
        reject_reasons=reasons,
        missing=missing,
        can_submit=can_submit,
    )


def _location_fresh(profile: WorkerProfile) -> bool:
    if not profile.location_updated_at or profile.current_latitude is None:
        return False
    if not settings.location_max_age_minutes:
        return True
    return now_vn() - profile.location_updated_at <= timedelta(minutes=settings.location_max_age_minutes)


def blockers(db: Session, user: User, profile: WorkerProfile, skills_count: int | None = None, balance: int | None = None) -> list[str]:
    """Lý do thợ chưa thể bật nhận đơn (rỗng = được bật)."""
    if skills_count is None:
        skills_count = db.scalar(select(func.count()).select_from(WorkerService).where(WorkerService.worker_id == user.id))
    if balance is None:
        balance = ws.wallet_balance(db, user.id)
    out = []
    if profile.verification_status != "approved":
        out.append("Hồ sơ chưa được duyệt")
    if not user.phone:
        out.append("Chưa có số điện thoại liên hệ")
    if not skills_count:
        out.append("Chưa chọn dịch vụ nhận làm")
    if ws.is_wallet_restricted(balance):
        out.append(f"Ví đang âm quá {ws.money(settings.wallet_debt_limit)}, hãy nạp tiền để tiếp tục nhận đơn")
    return out


# ---------- Hồ sơ ----------


def me(db: Session, user: User):
    profile = get_profile(db, user)
    skills = _skills(db, user.id)
    docs = _documents(db, user.id)
    rating = rating_avg(db, user.id)
    return success(
        WorkerMe(
            user=UserOut.model_validate(user),
            profile=WorkerProfileData(
                bio=profile.bio,
                experience_years=profile.experience_years,
                service_radius_km=float(profile.service_radius_km),
                availability=profile.availability,
                verification_status=profile.verification_status,
                trust_score=float(profile.trust_score),
                review_count=profile.review_count,
                completed_orders=profile.completed_orders,
                rating_avg=rating,
                current_latitude=profile.current_latitude,
                current_longitude=profile.current_longitude,
                location_updated_at=profile.location_updated_at,
                submitted_at=profile.submitted_at,
                level=WorkerLevel(**ws.worker_level(profile.completed_orders or 0, rating)),
            ),
            skills=skills,
            documents=[WorkerDocumentOut.model_validate(d) for d in docs],
            bank_account=_bank(db, user.id),
            onboarding=_onboarding(user, profile, len(skills), docs),
            settings=AppSettings(
                commission_rate=settings.commission_rate,
                min_withdrawal=settings.min_withdrawal,
                wallet_debt_limit=settings.wallet_debt_limit,
                location_max_age_minutes=settings.location_max_age_minutes,
                warranty_days=settings.warranty_days,
            ),
        )
    )


def update_profile(db: Session, user: User, data: WorkerProfileUpdate):
    fields = data.model_dump(exclude_unset=True)
    profile = get_profile(db, user)
    if "phone" in fields:
        if not fields["phone"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Số điện thoại không được trống")
        if fields["phone"] != user.phone and db.scalar(
            select(User.id).where(User.phone == fields["phone"], User.id != user.id)
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Số điện thoại đã được dùng cho tài khoản khác")
    if "full_name" in fields and not fields["full_name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Họ tên không được trống")

    for key in ("full_name", "phone", "avatar_url"):
        if key in fields:
            setattr(user, key, fields[key])
    for key in ("bio", "experience_years", "service_radius_km"):
        if key in fields and fields[key] is not None:
            setattr(profile, key, fields[key])
    if "bio" in fields and fields["bio"] is None:
        profile.bio = None
    db.commit()
    return me(db, user)


def set_skills(db: Session, user: User, data: WorkerSkillsUpdate):
    ids = sorted(set(data.service_ids))
    valid = set(
        db.scalars(
            select(Service.id)
            .join(ServiceCategory, ServiceCategory.id == Service.category_id)
            .where(Service.id.in_(ids), Service.is_active.is_(True), ServiceCategory.is_active.is_(True))
        ).all()
    )
    if len(valid) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Có dịch vụ không tồn tại hoặc đã ngừng")
    get_profile(db, user)
    db.execute(delete(WorkerService).where(WorkerService.worker_id == user.id))
    db.add_all([WorkerService(worker_id=user.id, service_id=sid) for sid in ids])
    db.commit()
    return success(_skills(db, user.id), "Đã cập nhật dịch vụ nhận làm")


# ---------- Giấy tờ xác minh ----------


def list_documents(db: Session, user: User):
    return success([WorkerDocumentOut.model_validate(d) for d in _documents(db, user.id)])


def add_document(db: Session, user: User, data: WorkerDocumentCreate):
    get_profile(db, user)
    if not data.file_url.startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đường dẫn ảnh không hợp lệ")
    now = now_vn()
    if data.doc_type == "certificate":
        count = db.scalar(
            select(func.count())
            .select_from(WorkerDocument)
            .where(
                WorkerDocument.worker_id == user.id,
                WorkerDocument.doc_type == "certificate",
                WorkerDocument.status != "rejected",
            )
        )
        if count >= MAX_CERTIFICATES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tối đa {MAX_CERTIFICATES} chứng chỉ")
        doc = WorkerDocument(worker_id=user.id, doc_type="certificate", file_url=data.file_url, uploaded_at=now)
        db.add(doc)
    else:
        # Giấy tờ bắt buộc đã duyệt vẫn cập nhật được (VD làm CCCD mới) nhưng KHÔNG thay ngay:
        # ảnh mới ở trạng thái chờ duyệt, ảnh cũ vẫn có hiệu lực cho tới khi admin duyệt ảnh mới
        # -> chống mạo danh/chiếm tài khoản mà thợ vẫn nhận việc bình thường trong lúc chờ.
        # Nếu đang có bản chờ duyệt thì thay ảnh, không tạo bản trùng
        doc = db.scalar(
            select(WorkerDocument)
            .where(
                WorkerDocument.worker_id == user.id,
                WorkerDocument.doc_type == data.doc_type,
                WorkerDocument.status == "pending",
            )
            .order_by(WorkerDocument.uploaded_at.desc())
            .limit(1)
        )
        if doc:
            doc.file_url, doc.uploaded_at = data.file_url, now
        else:
            doc = WorkerDocument(worker_id=user.id, doc_type=data.doc_type, file_url=data.file_url, uploaded_at=now)
            db.add(doc)
    db.commit()
    db.refresh(doc)
    has_approved = data.doc_type != "certificate" and db.scalar(
        select(WorkerDocument.id).where(
            WorkerDocument.worker_id == user.id,
            WorkerDocument.doc_type == data.doc_type,
            WorkerDocument.status == "approved",
        )
    )
    msg = (
        f"Đã gửi ảnh {DOC_LABEL[data.doc_type]} mới, ảnh cũ vẫn dùng đến khi được duyệt"
        if has_approved
        else f"Đã tải lên {DOC_LABEL[data.doc_type]}"
    )
    return success(WorkerDocumentOut.model_validate(doc), msg)


def delete_document(db: Session, user: User, document_id: int):
    doc = db.get(WorkerDocument, document_id)
    if not doc or doc.worker_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy giấy tờ")
    # Chứng chỉ (không bắt buộc) gỡ được kể cả đã duyệt; CCCD/chân dung đã duyệt là căn cứ xác minh nên không gỡ,
    # muốn đổi thì gửi ảnh mới để duyệt lại. Bản chờ duyệt / bị từ chối thì gỡ thoải mái.
    if doc.status == "approved" and doc.doc_type != "certificate":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{DOC_LABEL.get(doc.doc_type, 'Giấy tờ')} đã duyệt không gỡ được. Muốn đổi, hãy gửi ảnh mới để duyệt lại",
        )
    db.delete(doc)
    db.commit()
    return success(message="Đã xóa giấy tờ")


def submit_verification(db: Session, user: User):
    profile = get_profile(db, user, for_update=True)
    skills_count = db.scalar(select(func.count()).select_from(WorkerService).where(WorkerService.worker_id == user.id))
    status_ = _onboarding(user, profile, skills_count, _documents(db, user.id))
    if profile.verification_status == "approved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hồ sơ đã được duyệt")
    if status_.missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hồ sơ còn thiếu: " + "; ".join(status_.missing))
    if not status_.can_submit:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hồ sơ đã được gửi, vui lòng chờ duyệt")

    profile.submitted_at = now_vn()
    profile.verification_status = "pending"
    for admin_id in db.scalars(select(User.id).where(User.role == "admin", User.status == "active")).all():
        notify(db, admin_id, "Hồ sơ thợ chờ duyệt", f"{user.full_name} vừa gửi hồ sơ xác minh", "worker_verification", user.id)
    db.commit()
    return me(db, user)


# ---------- Tài khoản ngân hàng ----------


def get_bank(db: Session, user: User):
    return success(_bank(db, user.id))


def set_bank(db: Session, user: User, data: BankAccountIn):
    get_profile(db, user)
    b = db.get(WorkerBankAccount, user.id)
    if b is None:
        b = WorkerBankAccount(worker_id=user.id)
        db.add(b)
    b.bank_name, b.account_number, b.account_holder = data.bank_name, data.account_number, data.account_holder
    b.updated_at = now_vn()
    db.commit()
    return success(_bank(db, user.id), "Đã lưu tài khoản ngân hàng")


# ---------- Bật/tắt nhận đơn, vị trí ----------


def _apply_location(db: Session, profile: WorkerProfile, lat: float, lng: float) -> None:
    now = now_vn()
    profile.current_latitude = lat
    profile.current_longitude = lng
    profile.location_updated_at = now
    # Đang làm đơn thì lưu vết đường đi (thưa bớt: tối đa 1 điểm / 20 giây)
    job_id = db.scalar(
        select(Order.id)
        .where(Order.worker_id == profile.user_id, Order.status.in_(ws.INFLIGHT_STATUSES))
        .order_by(Order.accepted_at.desc())
        .limit(1)
    )
    if job_id:
        last = db.scalar(
            select(func.max(WorkerLocationLog.recorded_at)).where(
                WorkerLocationLog.worker_id == profile.user_id
            )
        )
        if not last or (now - last).total_seconds() >= LOCATION_LOG_EVERY_SECONDS:
            db.add(WorkerLocationLog(worker_id=profile.user_id, order_id=job_id, latitude=lat, longitude=lng, recorded_at=now))


def update_location(db: Session, user: User, lat: float, lng: float):
    profile = get_profile(db, user)
    _apply_location(db, profile, lat, lng)
    db.commit()
    db.refresh(profile)  # đọc lại geohash do trigger trong DB tính
    return success(
        {
            "latitude": profile.current_latitude,
            "longitude": profile.current_longitude,
            "geohash": profile.geohash,
            "location_updated_at": profile.location_updated_at,
        },
        "Đã cập nhật vị trí",
    )


def set_availability(db: Session, user: User, data: AvailabilityUpdate):
    profile = get_profile(db, user, for_update=True)
    if data.latitude is not None:
        _apply_location(db, profile, data.latitude, data.longitude)

    if data.online:
        problems = blockers(db, user, profile)
        if problems:
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problems[0])
        if not _location_fresh(profile):
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cần bật định vị để nhận đơn quanh bạn")
        profile.availability = "online"
        ws.refresh_availability(db, user.id)
        msg = "Đã bật nhận đơn"
    else:
        profile.availability = "offline"
        dispatch_service.withdraw_worker_offers(db, user.id)
        msg = "Đã tắt nhận đơn"
    db.commit()
    return success(AvailabilityOut(availability=profile.availability, location_fresh=_location_fresh(profile)), msg)


# ---------- Trang chủ ----------


def home(db: Session, user: User):
    from app.controllers import worker_job_controller as jobs  # tránh import vòng

    profile = get_profile(db, user)
    now = now_vn()
    today = day_start(now)
    skills_count = db.scalar(select(func.count()).select_from(WorkerService).where(WorkerService.worker_id == user.id))
    balance = ws.wallet_balance(db, user.id)

    completed_today = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.worker_id == user.id, Order.status == "completed", Order.completed_at >= today)
    )
    net, gross = db.execute(
        select(
            func.coalesce(func.sum(WorkerEarning.net_amount), 0),
            func.coalesce(func.sum(WorkerEarning.gross_amount), 0),
        ).where(WorkerEarning.worker_id == user.id, WorkerEarning.created_at >= today)
    ).one()

    open_jobs = db.scalars(
        select(Order)
        .where(Order.worker_id == user.id, Order.status.in_(ws.OPEN_JOB_STATUSES))
        .order_by(Order.scheduled_at.asc().nulls_first(), Order.accepted_at)
    ).all()
    soon = now + timedelta(minutes=ws.BUSY_BEFORE_SCHEDULE_MINUTES)
    active = next((o for o in open_jobs if o.status in ws.INFLIGHT_STATUSES), None) or next(
        (o for o in open_jobs if o.scheduled_at is None or o.scheduled_at <= soon), None
    )
    upcoming = [o for o in open_jobs if o is not active][:5]
    items = jobs.job_items(db, user, ([active] if active else []) + upcoming)

    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
    )
    problems = blockers(db, user, profile, skills_count, balance)
    week_net, week_gross, week_done = db.execute(
        select(
            func.coalesce(func.sum(WorkerEarning.net_amount), 0),
            func.coalesce(func.sum(WorkerEarning.gross_amount), 0),
            func.count(WorkerEarning.id),
        ).where(WorkerEarning.worker_id == user.id, WorkerEarning.created_at >= today - timedelta(days=6))
    ).one()
    rating = rating_avg(db, user.id)
    has_loc = profile.current_latitude is not None and profile.current_longitude is not None
    return success(
        HomeOut(
            availability=profile.availability,
            verification_status=profile.verification_status,
            can_go_online=not problems,
            blockers=problems,
            location_fresh=_location_fresh(profile),
            today=TodayStats(completed=completed_today, net_income=int(net), gross_income=int(gross)),
            rating_avg=rating,
            review_count=profile.review_count,
            trust_score=float(profile.trust_score),
            wallet_balance=balance,
            wallet_restricted=ws.is_wallet_restricted(balance),
            current_offer=jobs.current_offer_out(db, user),
            active_job=items[0] if active else None,
            upcoming=items[1:] if active else items,
            unread_notifications=unread,
            matching_mode=load_active_config(db).mode,
            location=GeoPoint(
                latitude=profile.current_latitude, longitude=profile.current_longitude, updated_at=profile.location_updated_at
            )
            if has_loc
            else None,
            service_radius_km=float(profile.service_radius_km or 10),
            level=WorkerLevel(**ws.worker_level(profile.completed_orders or 0, rating)),
            week=TodayStats(completed=int(week_done), net_income=int(week_net), gross_income=int(week_gross)),
        )
    )


def offer_counts_for(db: Session, worker_id: int, since) -> dict[str, int]:
    rows = db.execute(
        select(OrderOffer.status, func.count())
        .where(OrderOffer.worker_id == worker_id, OrderOffer.sent_at >= since)
        .group_by(OrderOffer.status)
    ).all()
    return dict(rows)
