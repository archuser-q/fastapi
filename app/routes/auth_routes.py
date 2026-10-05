from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.controllers import auth_controller
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    return auth_controller.register(db, data)


@router.post("/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    return auth_controller.login(db, data, response)

@router.post("/logout")
def logout(response: Response):
    return auth_controller.logout(response)

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return auth_controller.get_me(user)


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return auth_controller.change_password(db, user, data)