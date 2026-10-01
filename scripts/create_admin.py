import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.utils.security import hash_password


def main():
    phone = input("Số điện thoại: ").strip()
    full_name = input("Họ tên: ").strip()
    password = getpass.getpass("Mật khẩu (8-72 ký tự): ")

    if not 8 <= len(password) <= 72:
        print("Mật khẩu phải từ 8 đến 72 ký tự")
        sys.exit(1)

    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.phone == phone)):
            print("Số điện thoại đã tồn tại")
            sys.exit(1)

        db.add(
            User(
                phone=phone,
                full_name=full_name,
                password_hash=hash_password(password),
                role="admin",
            )
        )
        db.commit()
        print("Đã tạo admin")
    finally:
        db.close()


if __name__ == "__main__":
    main()