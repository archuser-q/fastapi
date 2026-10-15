"""Áp dụng các file SQL trong db/migrations theo thứ tự tên, mỗi file đúng 1 lần.

    python -m db.migrate

- DB trống (chạy ngoài Docker): tự nạp db/schema.sql trước.
- DB do Docker tạo: schema.sql đã được nạp sẵn qua docker-entrypoint-initdb.d.
- Đã chạy rồi thì bỏ qua (ghi trong bảng schema_migrations).
"""

from pathlib import Path

from sqlalchemy import text

from app.database import engine

DB_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = DB_DIR / "migrations"
LOCK_KEY = 815_002  # khóa advisory để 2 tiến trình không chạy migrate cùng lúc


def _has_table(conn, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar())


def main() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            if not _has_table(conn, "users"):
                print("[migrate] DB trống -> nạp db/schema.sql")
                conn.exec_driver_sql((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
                conn.commit()

            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    " version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT NOW())"
                )
            )
            conn.commit()
            done = set(conn.execute(text("SELECT version FROM schema_migrations")).scalars())

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                print(f"[migrate] áp dụng {path.name}")
                conn.exec_driver_sql(path.read_text(encoding="utf-8"))
                conn.execute(text("INSERT INTO schema_migrations(version) VALUES (:v)"), {"v": path.name})
                conn.commit()
            print("[migrate] CSDL đã ở phiên bản mới nhất")
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.commit()


if __name__ == "__main__":
    main()
