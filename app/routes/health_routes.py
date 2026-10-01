from fastapi import APIRouter

from app.controllers import health_controller

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("")
def health():
    return health_controller.check_health()