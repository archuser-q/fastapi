from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.schemas.admin import CreateStaffRequest
from app.schemas.user import UserOut
from app.utils.response import success
from app.utils.security import hash_password


def create_staff(db: Session, data: CreateStaffRequest):
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Số điện thoại đã được đăng ký")
    if data.email and db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email đã được đăng ký")

    user = User(
        phone=data.phone,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role="staff",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Tạo tài khoản nhân viên thành công")