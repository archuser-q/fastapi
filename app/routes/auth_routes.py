from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.controllers import auth_controller
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SocialLoginRequest,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    return auth_controller.register(db, data)


@router.post("/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    return auth_controller.login(db, data, response)


@router.get("/providers")
def providers():
    """Cấu hình đăng nhập Google/Facebook để app tự bật/tắt nút (client id không phải bí mật)."""
    return auth_controller.providers()


@router.post("/google")
def google_login(data: SocialLoginRequest, response: Response, db: Session = Depends(get_db)):
    """Đăng nhập/đăng ký bằng Google. Gửi id_token (hoặc access_token) lấy từ Google + role của app."""
    return auth_controller.social_login(db, "google", data, response)


@router.post("/facebook")
def facebook_login(data: SocialLoginRequest, response: Response, db: Session = Depends(get_db)):
    """Đăng nhập/đăng ký bằng Facebook. Gửi access_token lấy từ Facebook + role của app."""
    return auth_controller.social_login(db, "facebook", data, response)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    return auth_controller.forgot_password(db, data)


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    return auth_controller.reset_password(db, data)


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
