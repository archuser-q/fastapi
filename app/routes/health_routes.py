from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.controllers import health_controller
from app.database import get_db

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("")
def health():
    return health_controller.check_health()

@router.get("/db")
def health_db(db: Session = Depends(get_db)):
    return health_controller.check_db(db)