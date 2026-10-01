from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkerProfile(Base):
    __tablename__ = "worker_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    bio: Mapped[str | None] = mapped_column(Text)
    experience_years: Mapped[int] = mapped_column(Integer, server_default="0")
    verification_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    availability: Mapped[str] = mapped_column(String(20), server_default="offline")
    service_radius_km: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="10")
    current_latitude: Mapped[float | None] = mapped_column(Float)
    current_longitude: Mapped[float | None] = mapped_column(Float)
    geohash: Mapped[str | None] = mapped_column(String(12))
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    trust_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, server_default="0")
    completed_orders: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkerDocument(Base):
    __tablename__ = "worker_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker_profiles.user_id"))
    doc_type: Mapped[str] = mapped_column(String(30))
    file_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)