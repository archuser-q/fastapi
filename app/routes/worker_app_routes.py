"""API dành cho App Thợ (Thành viên B). Tất cả yêu cầu đăng nhập bằng tài khoản role = worker."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import worker_finance_controller as finance
from app.controllers import worker_job_controller as jobs
from app.controllers import worker_profile_controller as profile
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.geo import LocationUpdate
from app.schemas.worker_app import (
    AdvanceStatusRequest,
    AvailabilityUpdate,
    BankAccountIn,
    ExtraQuoteCreate,
    PhotoCreate,
    RejectOfferRequest,
    TopupCreate,
    WithdrawalCreate,
    WorkerCancelRequest,
    WorkerDocumentCreate,
    WorkerProfileUpdate,
    WorkerReportCreate,
    WorkerSkillsUpdate,
)

worker_only = require_roles("worker")

router = APIRouter(prefix="/worker", tags=["Worker App"])

Page = Query(1, ge=1)
PageSize = Query(20, ge=1, le=100)


# ---------- Hồ sơ & xác minh ----------


@router.get("/me")
def get_me(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Toàn bộ hồ sơ thợ + trạng thái các bước xác minh (onboarding)."""
    return profile.me(db, w)


@router.patch("/profile")
def update_profile(data: WorkerProfileUpdate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return profile.update_profile(db, w, data)


@router.put("/services")
def set_services(data: WorkerSkillsUpdate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Chọn các dịch vụ điện nhận làm (kỹ năng)."""
    return profile.set_skills(db, w, data)


@router.get("/documents")
def list_documents(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return profile.list_documents(db, w)


@router.post("/documents", status_code=201)
def add_document(data: WorkerDocumentCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Gửi giấy tờ (ảnh đã upload qua POST /uploads): CCCD 2 mặt, ảnh chân dung, chứng chỉ."""
    return profile.add_document(db, w, data)


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return profile.delete_document(db, w, document_id)


@router.post("/verification/submit")
def submit_verification(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Gửi hồ sơ cho admin xét duyệt."""
    return profile.submit_verification(db, w)


@router.get("/bank-account")
def get_bank(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return profile.get_bank(db, w)


@router.put("/bank-account")
def set_bank(data: BankAccountIn, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return profile.set_bank(db, w, data)


# ---------- Nhận đơn & vị trí ----------


@router.get("/home")
def home(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Dữ liệu màn Trang chủ: trạng thái, số liệu hôm nay, offer đang chờ, đơn đang làm, lịch sắp tới."""
    return profile.home(db, w)


@router.patch("/availability")
def set_availability(data: AvailabilityUpdate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Bật / tắt nhận đơn (gửi kèm toạ độ hiện tại khi bật)."""
    return profile.set_availability(db, w, data)


@router.patch("/location")
def update_location(data: LocationUpdate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """App gửi vị trí định kỳ khi đang bật nhận đơn hoặc đang làm đơn."""
    return profile.update_location(db, w, data.latitude, data.longitude)


@router.get("/offers/current")
def current_offer(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Lời mời nhận đơn đang chờ trả lời (null nếu không có). App hỏi định kỳ vài giây/lần khi bật nhận đơn."""
    return jobs.current_offer(db, w)


@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.accept_offer(db, w, offer_id)


@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: int, data: RejectOfferRequest, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.reject_offer(db, w, offer_id, data.reason)


# ---------- Đơn của tôi ----------


@router.get("/orders")
def list_orders(
    group: Literal["active", "completed", "cancelled", "history"] = "active",
    page: int = Page,
    page_size: int = PageSize,
    db: Session = Depends(get_db),
    w: User = Depends(worker_only),
):
    return jobs.list_jobs(db, w, group, page, page_size)


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.job_detail(db, w, order_id)


@router.post("/orders/{order_id}/status")
def advance_status(order_id: int, data: AdvanceStatusRequest, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Chuyển sang bước tiếp theo: on_the_way -> arrived -> in_progress -> completed."""
    return jobs.advance_status(db, w, order_id, data)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, data: WorkerCancelRequest, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.cancel_job(db, w, order_id, data)


@router.post("/orders/{order_id}/photos", status_code=201)
def add_photos(order_id: int, data: PhotoCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.add_photos(db, w, order_id, data)


@router.delete("/orders/{order_id}/photos/{photo_id}")
def delete_photo(order_id: int, photo_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.delete_photo(db, w, order_id, photo_id)


@router.post("/orders/{order_id}/extra-quotes", status_code=201)
def create_quote(order_id: int, data: ExtraQuoteCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Báo giá phát sinh (vật tư / công thêm) — khách duyệt trên app khách."""
    return jobs.create_quote(db, w, order_id, data)


@router.post("/orders/{order_id}/extra-quotes/{quote_id}/cancel")
def cancel_quote(order_id: int, quote_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.cancel_quote(db, w, order_id, quote_id)


@router.post("/orders/{order_id}/confirm-cash")
def confirm_cash(order_id: int, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Thợ xác nhận đã thu tiền mặt của khách."""
    return jobs.confirm_cash(db, w, order_id)


@router.post("/orders/{order_id}/report", status_code=201)
def report(order_id: int, data: WorkerReportCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Báo cáo sự cố (khách vắng mặt, không thanh toán...) — vào luồng khiếu nại của admin."""
    return jobs.create_report(db, w, order_id, data)


@router.get("/reports")
def list_reports(page: int = Page, page_size: int = PageSize, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return jobs.list_reports(db, w, page, page_size)


# ---------- Thu nhập & ví ----------


@router.get("/earnings/summary")
def earnings_summary(
    period: Literal["today", "week", "month"] = "week",
    db: Session = Depends(get_db),
    w: User = Depends(worker_only),
):
    return finance.earnings_summary(db, w, period)


@router.get("/earnings")
def earnings_history(page: int = Page, page_size: int = PageSize, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return finance.earnings_history(db, w, page, page_size)


@router.get("/wallet")
def wallet(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return finance.wallet(db, w)


@router.get("/wallet/transactions")
def wallet_transactions(page: int = Page, page_size: int = PageSize, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return finance.transactions(db, w, page, page_size)


@router.post("/wallet/withdrawals", status_code=201)
def create_withdrawal(data: WithdrawalCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Rút tiền về ngân hàng (mô phỏng)."""
    return finance.create_withdrawal(db, w, data)


@router.get("/wallet/withdrawals")
def list_withdrawals(page: int = Page, page_size: int = PageSize, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    return finance.list_withdrawals(db, w, page, page_size)


@router.post("/wallet/topup")
def topup(data: TopupCreate, db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Nạp tiền vào ví (sandbox, chỉ khi DEBUG=true)."""
    return finance.topup(db, w, data)


# ---------- Đánh giá & hiệu suất ----------


@router.get("/reviews")
def reviews(
    rating: int | None = Query(None, ge=1, le=5),
    page: int = Page,
    page_size: int = PageSize,
    db: Session = Depends(get_db),
    w: User = Depends(worker_only),
):
    return finance.reviews(db, w, rating, page, page_size)


@router.get("/performance")
def performance(db: Session = Depends(get_db), w: User = Depends(worker_only)):
    """Chỉ số 30 ngày: tỷ lệ nhận đơn, tỷ lệ hoàn thành, số lần hủy, điểm đánh giá, điểm tin cậy."""
    return finance.performance(db, w)
