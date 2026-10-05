from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, WorkerProfile
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.user import UserOut
from app.utils.response import success
from app.utils.security import create_access_token, hash_password, verify_password
from app.utils.cookies import clear_auth_cookie, set_auth_cookie


def register(db: Session, data: RegisterRequest):
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Số điện thoại đã được đăng ký")
    if data.email and db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email đã được đăng ký")

    user = User(
        phone=data.phone,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    db.flush()

    if data.role == "worker":
        db.add(WorkerProfile(user_id=user.id))

    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Đăng ký thành công")


def login(db: Session, data: LoginRequest, response: Response):
    user = db.scalar(select(User).where(User.phone == data.phone))
    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai số điện thoại hoặc mật khẩu")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản đã bị khóa")

    token = create_access_token(user.id, user.role)
    set_auth_cookie(response, token)
    return success(
        {"access_token": token, "token_type": "bearer", "user": UserOut.model_validate(user)},
        "Đăng nhập thành công",
    )

def logout(response: Response):
    clear_auth_cookie(response)
    return success(message="Đăng xuất thành công")

def get_me(user: User):
    return success(UserOut.model_validate(user))


def change_password(db: Session, user: User, data: ChangePasswordRequest):
    if not user.password_hash or not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu cũ không đúng")

    user.password_hash = hash_password(data.new_password)
    db.commit()
    return success(message="Đổi mật khẩu thành công")