"""Các bảng thêm cho App Thợ và bộ điều phối ghép cặp (migration 002)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkerBankAccount(Base):
    __tablename__ = "worker_bank_accounts"

    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"), primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(100))
    account_number: Mapped[str] = mapped_column(String(30))
    account_holder: Mapped[str] = mapped_column(String(150))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OrderPhoto(Base):
    __tablename__ = "order_photos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10))  # before | after
    url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OrderDispatch(Base):
    """Trạng thái tìm thợ của 1 đơn (hàng đợi của bộ điều phối)."""

    __tablename__ = "order_dispatches"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20))
    rounds: Mapped[int] = mapped_column(Integer, server_default="0")
    offers_sent: Mapped[int] = mapped_column(Integer, server_default="0")
    last_candidates: Mapped[int | None] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"))
    type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    withdrawal_id: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkerWithdrawal(Base):
    __tablename__ = "worker_withdrawals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_number: Mapped[str] = mapped_column(String(30))
    account_holder: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    transaction_code: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    processed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class WorkerLocationLog(Base):
    """Bảng có sẵn trong schema gốc (worker_location_logs): vết đường đi của thợ khi đang làm đơn."""

    __tablename__ = "worker_location_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
