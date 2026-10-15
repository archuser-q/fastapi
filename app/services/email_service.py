"""Gửi email (dùng cho mã đặt lại mật khẩu). Chưa cấu hình SMTP thì chỉ in ra log."""

import logging
import smtplib
import threading
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("thonhanh.email")


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
    except Exception:  # không để lỗi email làm hỏng request
        log.exception("Gửi email tới %s thất bại", to)


def send_email(to: str, subject: str, body: str) -> None:
    if not smtp_configured():
        log.warning("[EMAIL - chưa cấu hình SMTP] To: %s | %s\n%s", to, subject, body)
        print(f"[EMAIL - chưa cấu hình SMTP] To: {to} | {subject}\n{body}", flush=True)
        return
    threading.Thread(target=_send, args=(to, subject, body), daemon=True).start()
