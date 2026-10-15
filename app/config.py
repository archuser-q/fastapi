from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "THO NHANH API"
    debug: bool = True
    cors_origins: list[str] = []
    # Cho phép thêm các origin theo mẫu (VD: app web chạy trên IP LAN bất kỳ)
    cors_origin_regex: str | None = None
    database_url: str
    # Múi giờ của phiên làm việc với DB: để NOW() trong SQL trùng với now_vn() trong code
    db_timezone: str = "Asia/Ho_Chi_Minh"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    auth_cookie_name: str = "access_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None

    # ---------- Đăng nhập Google / Facebook ----------
    # Client ID của Google (web / android / ios). Backend chấp nhận id_token có aud thuộc danh sách này.
    google_web_client_id: str | None = None
    google_android_client_id: str | None = None
    google_ios_client_id: str | None = None
    facebook_app_id: str | None = None
    facebook_app_secret: str | None = None

    # ---------- Email (quên mật khẩu) ----------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    password_reset_code_minutes: int = 15

    # ---------- Upload ảnh ----------
    media_dir: str = "media"
    media_url_prefix: str = "/media"
    # Địa chỉ công khai của API (VD http://192.168.1.10:8000). Bỏ trống thì lấy theo request.
    public_base_url: str | None = None
    upload_max_mb: int = 8

    # ---------- Điều phối đơn / ghép cặp ----------
    dispatcher_enabled: bool = True
    dispatcher_tick_seconds: float = 2.0
    # Thợ không cập nhật vị trí quá số phút này thì không được ghép (app đã tắt / mất mạng)
    location_max_age_minutes: int = 10
    # Không có ứng viên thì bao lâu thử ghép lại
    dispatch_retry_seconds: int = 20
    # Đơn "đặt ngay" chờ tối đa bao lâu không có thợ nhận thì hệ thống tự hủy
    dispatch_max_wait_minutes: int = 15
    # Đơn hẹn giờ: nếu tới trước giờ hẹn bấy nhiêu phút mà chưa có thợ thì tự hủy
    scheduled_cancel_before_minutes: int = 15
    # Hai lịch hẹn của cùng 1 thợ phải cách nhau ít nhất (phút)
    schedule_conflict_minutes: int = 120
    # Nhắc thợ trước giờ hẹn (phút)
    schedule_reminder_minutes: int = 60

    # ---------- Thu nhập, ví ----------
    commission_rate: float = 0.15
    warranty_days: int = 30
    # Ví âm quá mức này (do hoa hồng đơn tiền mặt) thì tạm ngừng nhận đơn
    wallet_debt_limit: int = 500_000
    min_withdrawal: int = 50_000
    # Môi trường demo: yêu cầu rút tiền được duyệt ngay
    withdrawal_auto_approve: bool = True

    # ---------- Thông báo đẩy (Expo Push) ----------
    push_enabled: bool = False
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
