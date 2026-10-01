from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import User, WorkerDocument, WorkerProfile
from app.schemas.admin import (
    AdminWorkerDetail,
    AdminWorkerItem,
    ReviewDocumentRequest,
    UserStatusUpdate,
    WorkerVerificationRequest,
)
from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut, WorkerProfileOut
from app.utils.pagination import paginate
from app.utils.response import paginated, success

REQUIRED_DOCS = {"id_card_front", "id_card_back", "portrait"}

def list_users(db: Session, role, user_status, keyword, page, page_size):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if user_status:
        stmt = stmt.where(User.status == user_status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(User.full_name.ilike(like), User.phone.ilike(like), User.email.ilike(like))
        )
    stmt = stmt.order_by(User.id.desc())

    users, total = paginate(db, stmt, page, page_size)
    items = [UserOut.model_validate(u) for u in users]
    return paginated(items, total, page, page_size)


def get_user(db: Session, user_id: int):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng")
    return success(UserOut.model_validate(user))


def update_user_status(db: Session, admin: User, user_id: int, data: UserStatusUpdate):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng")
    if user.id == admin.id or user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không thể thay đổi trạng thái tài khoản admin")

    user.status = data.status
    if data.status == "blocked" and user.role == "worker":
        profile = db.get(WorkerProfile, user.id)
        if profile:
            profile.availability = "offline"

    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Cập nhật trạng thái thành công")


def list_workers(db: Session, verification_status, page, page_size):
    stmt = select(User).join(WorkerProfile, WorkerProfile.user_id == User.id)
    if verification_status:
        stmt = stmt.where(WorkerProfile.verification_status == verification_status)
    stmt = stmt.order_by(User.id.desc())

    users, total = paginate(db, stmt, page, page_size)
    profiles = {
        p.user_id: p
        for p in db.scalars(
            select(WorkerProfile).where(WorkerProfile.user_id.in_([u.id for u in users]))
        )
    }
    items = [
        AdminWorkerItem(
            user=UserOut.model_validate(u),
            profile=WorkerProfileOut.model_validate(profiles[u.id]),
        )
        for u in users
    ]
    return paginated(items, total, page, page_size)


def get_worker(db: Session, worker_id: int):
    user = db.get(User, worker_id)
    profile = db.get(WorkerProfile, worker_id)
    if not user or not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thợ")

    documents = db.scalars(
        select(WorkerDocument)
        .where(WorkerDocument.worker_id == worker_id)
        .order_by(WorkerDocument.uploaded_at.desc())
    ).all()
    detail = AdminWorkerDetail(
        user=UserOut.model_validate(user),
        profile=WorkerProfileOut.model_validate(profile),
        documents=[WorkerDocumentOut.model_validate(d) for d in documents],
    )
    return success(detail)


def review_document(db: Session, reviewer: User, document_id: int, data: ReviewDocumentRequest):
    doc = db.get(WorkerDocument, document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy giấy tờ")

    doc.status = data.status
    doc.reject_reason = data.reject_reason if data.status == "rejected" else None
    doc.reviewed_by = reviewer.id
    doc.reviewed_at = func.now()
    db.commit()
    db.refresh(doc)
    return success(WorkerDocumentOut.model_validate(doc), "Đã cập nhật giấy tờ")


def update_worker_verification(db: Session, worker_id: int, data: WorkerVerificationRequest):
    profile = db.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thợ")

    if data.status == "approved":
        approved = set(
            db.scalars(
                select(WorkerDocument.doc_type).where(
                    WorkerDocument.worker_id == worker_id,
                    WorkerDocument.status == "approved",
                )
            )
        )
        missing = REQUIRED_DOCS - approved
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Chưa duyệt đủ giấy tờ bắt buộc: " + ", ".join(sorted(missing)),
            )

    profile.verification_status = data.status
    if data.status != "approved":
        profile.availability = "offline"

    db.commit()
    db.refresh(profile)
    return success(WorkerProfileOut.model_validate(profile), "Đã cập nhật xác minh thợ")