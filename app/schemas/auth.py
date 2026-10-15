from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

AppRole = Literal["customer", "worker"]


def _strip_lower(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    return v or None


class RegisterRequest(BaseModel):
    """Đăng ký bằng mật khẩu. Nhóm đã chốt đăng nhập bằng Email (+ Google/Facebook);
    vẫn nhận `phone` để app/khách cũ đang đăng ký bằng SĐT không bị hỏng."""

    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^0\d{9}$")
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=150)
    role: AppRole = "customer"

    _email = field_validator("email", mode="before")(_strip_lower)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Họ tên không được trống")
        return v

    @model_validator(mode="after")
    def _need_contact(self):
        if not self.email and not self.phone:
            raise ValueError("Cần nhập email")
        return self


class LoginRequest(BaseModel):
    """Đăng nhập bằng email hoặc số điện thoại.

    - App mới gửi `identifier` (email hoặc SĐT) hoặc `email`.
    - Web quản trị / app khách cũ gửi `phone` -> vẫn chạy.
    - `role` (tuỳ chọn): app nào thì gửi role đó, sai role sẽ bị chặn ngay ở server.
    """

    identifier: str | None = None
    email: str | None = None
    phone: str | None = None
    password: str
    role: Literal["customer", "worker", "admin"] | None = None

    @model_validator(mode="after")
    def _need_identifier(self):
        if not (self.identifier or self.email or self.phone):
            raise ValueError("Cần nhập email hoặc số điện thoại")
        return self

    @property
    def login_id(self) -> str:
        return (self.identifier or self.email or self.phone or "").strip()


class SocialLoginRequest(BaseModel):
    """Google: gửi id_token (khuyên dùng) hoặc access_token. Facebook: gửi access_token."""

    id_token: str | None = Field(default=None, max_length=8192)
    access_token: str | None = Field(default=None, max_length=8192)
    role: AppRole = "customer"

    @model_validator(mode="after")
    def _need_token(self):
        if not self.id_token and not self.access_token:
            raise ValueError("Thiếu token đăng nhập")
        return self


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    _email = field_validator("email", mode="before")(_strip_lower)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=72)

    _email = field_validator("email", mode="before")(_strip_lower)


class ChangePasswordRequest(BaseModel):
    # Tài khoản tạo bằng Google/Facebook chưa có mật khẩu -> được đặt mới không cần mật khẩu cũ
    old_password: str | None = None
    new_password: str = Field(min_length=8, max_length=72)
