from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    transaction_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class WorkerEarning(Base):
    __tablename__ = "worker_earnings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
