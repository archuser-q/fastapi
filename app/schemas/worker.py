from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    bio: str | None
    experience_years: int
    verification_status: str
    availability: str
    service_radius_km: Decimal
    current_latitude: float | None
    current_longitude: float | None
    location_updated_at: datetime | None
    trust_score: Decimal
    review_count: int
    completed_orders: int
    created_at: datetime


class WorkerProfileUpdate(BaseModel):
    bio: str | None = None
    experience_years: int | None = Field(default=None, ge=0, le=60)
    service_radius_km: Decimal | None = Field(default=None, gt=0, le=100)


class WorkerAvailabilityUpdate(BaseModel):
    availability: Literal["online", "busy", "offline"]


class WorkerLocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class WorkerDocumentCreate(BaseModel):
    doc_type: Literal["id_card_front", "id_card_back", "certificate", "portrait"]
    file_url: str


class WorkerDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    worker_id: int
    doc_type: str
    file_url: str
    status: str
    reject_reason: str | None
    uploaded_at: datetime
    reviewed_at: datetime | None