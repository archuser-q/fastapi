"""Web quản trị: duyệt yêu cầu rút tiền của thợ (mô phỏng). Bạn làm web admin có thể gắn giao diện vào đây."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User, WalletTransaction, WorkerWithdrawal
from app.services.notification_service import notify
from app.services.worker_service import money
from app.utils.dates import now_vn
from app.utils.response import paginated, success

admin_only = require_roles("admin")
router = APIRouter(prefix="/admin/withdrawals", tags=["Admin - Withdrawals"], dependencies=[Depends(admin_only)])


class ProcessRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    transaction_code: str | None = Field(default=None, max_length=100)


def _out(w: WorkerWithdrawal, name: str | None = None) -> dict:
    return {
        "id": w.id,
        "worker_id": w.worker_id,
        "worker_name": name,
        "amount": int(w.amount),
        "bank_name": w.bank_name,
        "account_number": w.account_number,
        "account_holder": w.account_holder,
        "status": w.status,
        "transaction_code": w.transaction_code,
        "note": w.note,
        "created_at": w.created_at,
        "processed_at": w.processed_at,
    }


@router.get("")
def list_withdrawals(
    withdrawal_status: Literal["pending", "completed", "rejected"] | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(WorkerWithdrawal, User.full_name).join(User, User.id == WorkerWithdrawal.worker_id)
    if withdrawal_status:
        stmt = stmt.where(WorkerWithdrawal.status == withdrawal_status)
    stmt = stmt.order_by(WorkerWithdrawal.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return paginated([_out(w, n) for w, n in rows], total, page, page_size)


def _get_pending(db: Session, withdrawal_id: int) -> WorkerWithdrawal:
    w = db.scalar(select(WorkerWithdrawal).where(WorkerWithdrawal.id == withdrawal_id).with_for_update())
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy yêu cầu rút tiền")
    if w.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Yêu cầu đã được xử lý")
    return w


@router.post("/{withdrawal_id}/approve")
def approve(withdrawal_id: int, data: ProcessRequest, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    w = _get_pending(db, withdrawal_id)
    w.status, w.processed_at, w.processed_by = "completed", now_vn(), admin.id
    w.transaction_code, w.note = data.transaction_code, data.note
    notify(db, w.worker_id, "Rút tiền thành công", f"{money(w.amount)} đã chuyển về {w.bank_name}", "withdrawal", w.id)
    db.commit()
    return success(_out(w), "Đã duyệt rút tiền")


@router.post("/{withdrawal_id}/reject")
def reject(withdrawal_id: int, data: ProcessRequest, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    w = _get_pending(db, withdrawal_id)
    now = now_vn()
    w.status, w.processed_at, w.processed_by, w.note = "rejected", now, admin.id, data.note
    # Hoàn lại tiền đã tạm trừ khỏi ví
    db.add(
        WalletTransaction(
            worker_id=w.worker_id,
            type="withdrawal_refund",
            amount=w.amount,
            withdrawal_id=w.id,
            description=f"Hoàn tiền yêu cầu rút #{w.id}" + (f": {data.note}" if data.note else ""),
            created_at=now,
        )
    )
    notify(db, w.worker_id, "Yêu cầu rút tiền bị từ chối", data.note or "Tiền đã được hoàn lại vào ví", "withdrawal", w.id)
    db.commit()
    return success(_out(w), "Đã từ chối và hoàn tiền vào ví")
