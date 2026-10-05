"""Tìm thợ ở gần bằng chỉ mục không gian PostGIS.

Đây là bước 1 (lọc ứng viên) của thuật toán ghép thợ. Bước 2 (chấm điểm theo
matching_configs) dùng lại distance_km trả về ở đây, không phải tính lại.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.geo import NearbyWorker

# ST_DWithin(..., :radius_m) dùng được chỉ mục GiST idx_worker_profiles_location.
# Điều kiện thứ hai đảm bảo khách cũng nằm trong bán kính nhận việc mà thợ tự đặt.
# ORDER BY location <-> điểm là phép tìm láng giềng gần nhất (KNN), cũng chạy trên chỉ mục.
NEARBY_WORKERS_SQL = text(
    """
    WITH target AS (
        SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS pt
    )
    SELECT
        wp.user_id AS worker_id,
        u.full_name,
        u.phone,
        wp.availability,
        wp.trust_score,
        wp.service_radius_km,
        ST_Distance(wp.location, target.pt) / 1000.0 AS distance_km,
        wp.location_updated_at
    FROM worker_profiles wp
    JOIN users u ON u.id = wp.user_id
    CROSS JOIN target
    WHERE wp.location IS NOT NULL
      AND ST_DWithin(wp.location, target.pt, :radius_m)
      AND ST_DWithin(wp.location, target.pt, wp.service_radius_km * 1000)
      AND wp.verification_status = 'approved'
      AND u.status = 'active'
      AND wp.availability = ANY(:statuses)
      AND (
          CAST(:service_id AS BIGINT) IS NULL
          OR EXISTS (
              SELECT 1 FROM worker_services ws
              WHERE ws.worker_id = wp.user_id AND ws.service_id = CAST(:service_id AS BIGINT)
          )
      )
      AND (
          CAST(:fresh_after AS TIMESTAMP) IS NULL
          OR wp.location_updated_at >= CAST(:fresh_after AS TIMESTAMP)
      )
    ORDER BY wp.location <-> target.pt
    LIMIT :limit
    """
)


def find_nearby_workers(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float,
    service_id: int | None = None,
    statuses: tuple[str, ...] = ("online",),
    fresh_after: datetime | None = None,
    limit: int = 50,
) -> list[NearbyWorker]:
    """Trả về các thợ đủ điều kiện trong bán kính radius_km, sắp xếp từ gần đến xa.

    - statuses: tình trạng làm việc được chấp nhận, mặc định chỉ thợ đang trực tuyến
    - fresh_after: bỏ qua thợ có vị trí cập nhật trước thời điểm này (vị trí đã cũ)
    """
    rows = db.execute(
        NEARBY_WORKERS_SQL,
        {
            "lat": latitude,
            "lng": longitude,
            "radius_m": radius_km * 1000,
            "statuses": list(statuses),
            "service_id": service_id,
            "fresh_after": fresh_after,
            "limit": limit,
        },
    ).mappings()
    return [
        NearbyWorker(
            worker_id=r["worker_id"],
            full_name=r["full_name"],
            phone=r["phone"],
            availability=r["availability"],
            trust_score=float(r["trust_score"]),
            service_radius_km=float(r["service_radius_km"]),
            distance_km=round(float(r["distance_km"]), 3),
            location_updated_at=r["location_updated_at"],
        )
        for r in rows
    ]
