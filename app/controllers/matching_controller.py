from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import MatchingConfig, Order, Service, User
from app.schemas.matching import (
    MatchingConfigCreate,
    MatchingConfigItem,
    MatchingConfigUpdate,
    RankedWorker,
    ScoreParts,
    SimulateRequest,
    SimulateResult,
    SimulateTarget,
    Weights,
)
from app.services.matching_service import MatchingParams, rank_workers
from app.utils.dates import now_vn
from app.utils.response import success


def _to_item(db: Session, c: MatchingConfig) -> MatchingConfigItem:
    editor = db.get(User, c.updated_by) if c.updated_by else None
    return MatchingConfigItem(
        id=c.id,
        name=c.name,
        mode=c.mode,
        weight_distance=float(c.weight_distance),
        weight_trust=float(c.weight_trust),
        weight_price=float(c.weight_price),
        weight_workload=float(c.weight_workload),
        batch_window_seconds=c.batch_window_seconds,
        search_radius_km=float(c.search_radius_km),
        max_offers=c.max_offers,
        offer_timeout_seconds=c.offer_timeout_seconds,
        is_active=c.is_active,
        updated_by_name=editor.full_name if editor else None,
        updated_at=c.updated_at,
    )


def _get_config(db: Session, config_id: int) -> MatchingConfig:
    config = db.get(MatchingConfig, config_id)
    if not config:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy cấu hình")
    return config


def _ensure_unique_name(db: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(MatchingConfig.id).where(MatchingConfig.name.ilike(name.strip()))
    if exclude_id:
        stmt = stmt.where(MatchingConfig.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Đã có cấu hình tên \"{name.strip()}\"")


# ---------- Quản lý cấu hình ----------


def list_configs(db: Session):
    configs = db.scalars(
        select(MatchingConfig).order_by(MatchingConfig.is_active.desc(), MatchingConfig.updated_at.desc())
    ).all()
    return success([_to_item(db, c) for c in configs])


def create_config(db: Session, admin: User, data: MatchingConfigCreate):
    _ensure_unique_name(db, data.name)
    config = MatchingConfig(
        **data.model_dump(),
        is_active=False,
        updated_by=admin.id,
        updated_at=now_vn(),
    )
    config.name = data.name.strip()
    db.add(config)
    db.commit()
    return success(_to_item(db, config), "Đã tạo cấu hình")


def update_config(db: Session, admin: User, config_id: int, data: MatchingConfigUpdate):
    config = _get_config(db, config_id)
    _ensure_unique_name(db, data.name, exclude_id=config_id)
    for key, value in data.model_dump().items():
        setattr(config, key, value)
    config.name = data.name.strip()
    config.updated_by = admin.id
    config.updated_at = now_vn()
    db.commit()
    message = (
        "Đã lưu, cấu hình mới có hiệu lực ngay với các đơn tiếp theo"
        if config.is_active
        else "Đã lưu cấu hình"
    )
    return success(_to_item(db, config), message)


def activate_config(db: Session, admin: User, config_id: int):
    config = _get_config(db, config_id)
    if config.is_active:
        return success(_to_item(db, config), "Cấu hình này đang được áp dụng")
    # Tắt cấu hình cũ trước khi bật cấu hình mới, cùng một giao dịch
    db.execute(update(MatchingConfig).where(MatchingConfig.is_active.is_(True)).values(is_active=False))
    db.flush()
    config.is_active = True
    config.updated_by = admin.id
    config.updated_at = now_vn()
    db.commit()
    return success(_to_item(db, config), f"Đã áp dụng cấu hình \"{config.name}\"")


def delete_config(db: Session, config_id: int):
    config = _get_config(db, config_id)
    if config.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Không xóa được cấu hình đang áp dụng, hãy áp dụng cấu hình khác trước",
        )
    db.delete(config)
    db.commit()
    return success(message="Đã xóa cấu hình")


# ---------- Mô phỏng ----------


def simulate(db: Session, data: SimulateRequest):
    # Cấu hình: chọn cụ thể, hoặc cấu hình đang áp dụng
    if data.config_id:
        config = _get_config(db, data.config_id)
    else:
        config = db.scalar(select(MatchingConfig).where(MatchingConfig.is_active.is_(True)))
        if not config:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chưa có cấu hình nào đang áp dụng")

    # Vị trí và dịch vụ: lấy từ đơn hàng nếu có
    order_id, latitude, longitude, service_id = None, data.latitude, data.longitude, data.service_id
    if data.order_id:
        order = db.get(Order, data.order_id)
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Không tìm thấy đơn #{data.order_id}")
        order_id, latitude, longitude, service_id = order.id, order.latitude, order.longitude, order.service_id
    service = db.get(Service, service_id) if service_id else None
    if service_id and not service:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy dịch vụ")

    weights = data.weights or Weights(
        weight_distance=float(config.weight_distance),
        weight_trust=float(config.weight_trust),
        weight_price=float(config.weight_price),
        weight_workload=float(config.weight_workload),
    )
    params = MatchingParams(
        **weights.model_dump(),
        search_radius_km=data.search_radius_km or float(config.search_radius_km),
        max_offers=config.max_offers,
    )

    ranked = rank_workers(db, latitude, longitude, service_id, params, include_busy=data.include_busy)

    def parts(values: dict[str, float]) -> ScoreParts:
        return ScoreParts(**{k: round(v, 4) for k, v in values.items()})

    return success(
        SimulateResult(
            target=SimulateTarget(
                order_id=order_id,
                latitude=latitude,
                longitude=longitude,
                service_id=service_id,
                service_name=service.name if service else None,
            ),
            config_name=config.name + (" (trọng số tùy chỉnh)" if data.weights else ""),
            mode=config.mode,
            weights=weights,
            search_radius_km=params.search_radius_km,
            max_offers=params.max_offers,
            candidates_found=len(ranked),
            ranking=[
                RankedWorker(
                    rank=i + 1,
                    worker_id=s.worker.worker_id,
                    full_name=s.worker.full_name,
                    phone=s.worker.phone,
                    availability=s.worker.availability,
                    distance_km=s.worker.distance_km,
                    active_orders=s.active_orders,
                    price_ratio=round(s.price_ratio, 3) if s.price_ratio is not None else None,
                    scores=parts(s.scores),
                    contributions=parts(s.contributions),
                    total_score=round(s.total, 4),
                    will_receive_offer=i < params.max_offers,
                )
                for i, s in enumerate(ranked)
            ],
        )
    )
