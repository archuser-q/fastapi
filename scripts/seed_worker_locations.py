"""Gán vị trí demo cho thợ đã duyệt, quanh Hồ Gươm (Hà Nội), để thử tìm thợ ở gần.

Chạy:  python -m scripts.seed_worker_locations
Thêm --force để gán lại cả những thợ đã có vị trí.
"""

import math
import random
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import WorkerProfile
from app.utils.dates import now_vn

CENTER = (21.0285, 105.8542)  # Hồ Gươm
MAX_KM = 8


def random_point(lat: float, lng: float, max_km: float) -> tuple[float, float]:
    # Lấy căn bậc hai để các điểm rải đều trên hình tròn, không dồn vào tâm
    distance = max_km * math.sqrt(random.random())
    bearing = random.uniform(0, 2 * math.pi)
    d_lat = distance / 111.32 * math.cos(bearing)
    d_lng = distance / (111.32 * math.cos(math.radians(lat))) * math.sin(bearing)
    return round(lat + d_lat, 6), round(lng + d_lng, 6)


def main():
    force = "--force" in sys.argv
    db = SessionLocal()
    try:
        stmt = select(WorkerProfile).where(WorkerProfile.verification_status == "approved")
        if not force:
            stmt = stmt.where(WorkerProfile.current_latitude.is_(None))
        workers = db.scalars(stmt).all()
        for w in workers:
            w.current_latitude, w.current_longitude = random_point(*CENTER, MAX_KM)
            w.location_updated_at = now_vn()
        db.commit()
        print(f"Đã gán vị trí cho {len(workers)} thợ trong bán kính {MAX_KM} km quanh Hồ Gươm")
    finally:
        db.close()


if __name__ == "__main__":
    main()
