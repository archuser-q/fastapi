from datetime import datetime

from pydantic import BaseModel, Field


class LocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class LocationOut(BaseModel):
    latitude: float
    longitude: float
    geohash: str | None
    location_updated_at: datetime


class NearbyWorker(BaseModel):
    worker_id: int
    full_name: str
    phone: str
    availability: str
    trust_score: float
    service_radius_km: float
    distance_km: float
    location_updated_at: datetime | None
