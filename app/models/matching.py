from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MatchingConfig(Base):
    __tablename__ = "matching_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))
    weight_distance: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    weight_trust: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    weight_price: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    weight_workload: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    batch_window_seconds: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
