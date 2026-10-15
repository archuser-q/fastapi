import secrets
from datetime import timedelta

from fastapi import HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PasswordResetCode, SocialAccount, User, WorkerProfile
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SocialLoginRequest,
)
from app.schemas.user import UserOut
from app.services import social_auth
from app.services.email_service import send_email, smtp_configured
from app.utils.cookies import clear_auth_cookie, set_auth_cookie
from app.utils.dates import now_vn
from app.utils.response import success
from app.utils.security import create_access_token, hash_password, verify_password

ROLE_LABEL = {"customer": "khách hàng", "worker": "thợ", "admin": "quản trị"}
MAX_RESET_ATTEMPTS = 5
RESET_COOLDOWN_SECONDS = 60


def _find_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def _check_role(user: User, expected: str | None) -> None:
    if expected and user.role != expected:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Đây là tài khoản {ROLE_LABEL.get(user.role, user.role)}, "
            f"không dùng được cho app {ROLE_LABEL.get(expected, expected)}",
        )


def _check_active(user: User) -> None:
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản đã bị khóa, vui lòng liên hệ CSKH")


def _token_response(user: User, response: Response, message: str, extra: dict | None = None):
    token = create_access_token(user.id, user.role)
    set_auth_cookie(response, token)
    data = {"access_token": token, "token_type": "bearer", "user": UserOut.model_validate(user)}
    if extra:
        data.update(extra)
    return success(data, message)


def _create_user(db: Session, *, role: str, full_name: str, email=None, phone=None, password=None, avatar_url=None) -> User:
    user = User(
        phone=phone,
        email=email,
        password_hash=hash_password(password) if password else None,
        full_name=full_name,
        avatar_url=avatar_url,
        role=role,
    )
    db.add(user)
    db.flush()
    if role == "worker":
        db.add(WorkerProfile(user_id=user.id))
    return user


# ---------- Đăng ký / đăng nhập bằng mật khẩu ----------


def register(db: Session, data: RegisterRequest):
    if data.phone and db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Số điện thoại đã được đăng ký")
    if data.email and _find_by_email(db, data.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email đã được đăng ký")

    user = _create_user(
        db, role=data.role, full_name=data.full_name, email=data.email, phone=data.phone, password=data.password
    )
    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Đăng ký thành công")


def login(db: Session, data: LoginRequest, response: Response):
    login_id = data.login_id
    if "@" in login_id:
        user = _find_by_email(db, login_id)
        wrong = "Sai email hoặc mật khẩu"
    else:
        user = db.scalar(select(User).where(User.phone == login_id))
        wrong = "Sai số điện thoại hoặc mật khẩu"

    if user and not user.password_hash:
        providers = db.scalars(select(SocialAccount.provider).where(SocialAccount.user_id == user.id)).all()
        if providers:
            names = " / ".join(sorted({p.capitalize() for p in providers}))
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                f"Tài khoản này đăng nhập bằng {names}. Bấm nút {names} để đăng nhập.",
            )
    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, wrong)
    _check_active(user)
    _check_role(user, data.role)
    return _token_response(user, response, "Đăng nhập thành công")


def logout(response: Response):
    clear_auth_cookie(response)
    return success(message="Đăng xuất thành công")


def get_me(user: User):
    return success(UserOut.model_validate(user))


def change_password(db: Session, user: User, data: ChangePasswordRequest):
    if user.password_hash:
        if not data.old_password or not verify_password(data.old_password, user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu cũ không đúng")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return success(message="Đổi mật khẩu thành công")


# ---------- Google / Facebook ----------


def providers():
    google = social_auth.google_client_ids()
    return success(
        {
            "google": {
                "web_client_id": settings.google_web_client_id,
                "android_client_id": settings.google_android_client_id,
                "ios_client_id": settings.google_ios_client_id,
            }
            if google
            else None,
            "facebook": {"app_id": settings.facebook_app_id} if social_auth.facebook_enabled() else None,
            "password_reset_by_email": True,
            "smtp_configured": smtp_configured(),
        }
    )


def social_login(db: Session, provider: str, data: SocialLoginRequest, response: Response):
    if provider == "google":
        profile = social_auth.verify_google(data.id_token, data.access_token)
    else:
        if not data.access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Facebook cần access_token")
        profile = social_auth.verify_facebook(data.access_token)

    link = db.scalar(
        select(SocialAccount).where(
            SocialAccount.provider == profile.provider,
            SocialAccount.provider_user_id == profile.provider_user_id,
        )
    )
    is_new = False
    if link:
        user = db.get(User, link.user_id)
    else:
        user = _find_by_email(db, profile.email) if profile.email and profile.email_verified else None
        if user is None:
            _guard_role_for_new(data.role)
            user = _create_user(
                db,
                role=data.role,
                full_name=(profile.full_name or (profile.email or "Người dùng").split("@")[0])[:150],
                email=profile.email if profile.email_verified else None,
                avatar_url=profile.avatar_url,
            )
            is_new = True
        _check_role(user, data.role)
        db.add(SocialAccount(user_id=user.id, provider=profile.provider, provider_user_id=profile.provider_user_id))
        if not user.avatar_url and profile.avatar_url:
            user.avatar_url = profile.avatar_url

    _check_active(user)
    _check_role(user, data.role)
    db.commit()
    db.refresh(user)
    return _token_response(user, response, "Đăng nhập thành công", {"is_new": is_new})


def _guard_role_for_new(role: str) -> None:
    if role not in ("customer", "worker"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vai trò không hợp lệ")


# ---------- Quên mật khẩu ----------


def forgot_password(db: Session, data: ForgotPasswordRequest):
    generic = "Nếu email đã đăng ký, mã xác nhận gồm 6 chữ số đã được gửi tới hộp thư (hiệu lực {} phút)".format(
        settings.password_reset_code_minutes
    )
    user = _find_by_email(db, data.email)
    if not user or user.status != "active":
        return success(None, generic)

    now = now_vn()
    last = db.scalar(
        select(PasswordResetCode.created_at)
        .where(PasswordResetCode.user_id == user.id)
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    )
    if last and (now - last).total_seconds() < RESET_COOLDOWN_SECONDS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Vui lòng chờ 1 phút rồi gửi lại mã")

    code = f"{secrets.randbelow(10**6):06d}"
    # Mã cũ chưa dùng hết hiệu lực
    db.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None))
        .values(used_at=now)
    )
    db.add(
        PasswordResetCode(
            user_id=user.id,
            code_hash=hash_password(code),
            expires_at=now + timedelta(minutes=settings.password_reset_code_minutes),
        )
    )
    db.commit()
    send_email(
        user.email,
        "[Thợ Nhanh] Mã đặt lại mật khẩu",
        f"Xin chào {user.full_name},\n\nMã đặt lại mật khẩu của bạn là: {code}\n"
        f"Mã có hiệu lực trong {settings.password_reset_code_minutes} phút. "
        "Nếu bạn không yêu cầu, hãy bỏ qua email này.\n\nThợ Nhanh",
    )
    # Môi trường dev chưa có SMTP: trả mã về để test (KHÔNG bật DEBUG khi chạy thật)
    extra = {"debug_code": code} if settings.debug and not smtp_configured() else None
    return success(extra, generic)


def reset_password(db: Session, data: ResetPasswordRequest):
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "Mã xác nhận không đúng hoặc đã hết hạn")
    user = _find_by_email(db, data.email)
    if not user:
        raise invalid
    rec = db.scalar(
        select(PasswordResetCode)
        .where(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None))
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    now = now_vn()
    if not rec or rec.expires_at < now or rec.attempts >= MAX_RESET_ATTEMPTS:
        raise invalid
    if not verify_password(data.code, rec.code_hash):
        rec.attempts += 1
        db.commit()
        raise invalid

    rec.used_at = now
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return success(message="Đặt lại mật khẩu thành công, hãy đăng nhập bằng mật khẩu mới")
