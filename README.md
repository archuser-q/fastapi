# THO NHANH API

REST API backend for **THO NHANH**, a home repair services platform that connects customers with nearby repair workers.

Built with **FastAPI**, **SQLAlchemy** and **PostgreSQL/PostGIS**, containerized with **Docker Compose**.

## Features

- **Nearby worker search**: finds nearby workers using PostGIS spatial queries (GiST index, KNN).
- **Authentication**: JWT (Bearer header or HTTP-only cookie) with role-based access control (`customer`, `worker`, `admin`).
- **Admin APIs**: manage orders, service catalog, reviews, complaints and dashboard statistics.
- **Worker app APIs**: endpoints for the worker mobile/web client.

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Language   | Python 3.12                         |
| Framework  | FastAPI, Pydantic                   |
| ORM        | SQLAlchemy 2                        |
| Database   | PostgreSQL 16 + PostGIS 3.4         |
| Auth       | PyJWT, bcrypt                       |
| DevOps     | Docker, Docker Compose              |

## Project Structure

```
.
├── app/
│   ├── controllers/   # Request handling logic
│   ├── routes/        # API routers (mounted under /api/v1)
│   ├── services/      # Business logic (geo search)
│   ├── models/        # SQLAlchemy models
│   ├── schemas/       # Pydantic request/response schemas
│   ├── middleware/    # Auth (JWT, RBAC), CORS
│   ├── utils/         # Security, pagination, responses
│   ├── config.py      # Settings loaded from .env
│   └── main.py        # App entry point
├── db/schema.sql      # Database schema (auto-loaded by Docker)
├── scripts/           # Admin & demo data scripts
├── Dockerfile
└── docker-compose.yml
```

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

### 1. Clone the repository

```bash
git clone https://github.com/archuser-q/<repo-name>.git
cd <repo-name>
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env` and set real values:

| Variable            | Description                                  |
|---------------------|----------------------------------------------|
| `POSTGRES_USER`     | Database user                                |
| `POSTGRES_PASSWORD` | Database password                            |
| `POSTGRES_DB`       | Database name                                |
| `JWT_SECRET`        | Secret key for signing JWT tokens (required) |
| `CORS_ORIGINS`      | Allowed frontend origins (JSON list)         |
| `DEBUG`             | `true` / `false`                             |

> `.env` is git-ignored. Never commit real credentials.

### 3. Run

```bash
docker compose up -d --build
```

On first run, `db/schema.sql` is loaded automatically into the database.

### 4. Open the API docs

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## Useful Commands

```bash
# Create an admin account
docker compose exec api python -m scripts.create_admin

# Seed demo locations for approved workers (around Hoan Kiem, Hanoi)
docker compose exec api python -m scripts.seed_worker_locations

# View API logs
docker compose logs -f api

# Stop containers
docker compose down

# Stop and wipe the database (re-runs schema.sql on next start)
docker compose down -v
```

## Nearby Worker Search

Uses PostGIS `ST_DWithin` and KNN ordering (`<->`) on a GiST index to find approved, online workers offering the requested service within the search radius, sorted by distance.
---

## Phần App Thợ & thuật toán ghép cặp (thành viên B)

> Tài liệu cho nhóm: [`docs/TICH_HOP_CHO_NHOM.md`](docs/TICH_HOP_CHO_NHOM.md) (file nào đã sửa, việc cần làm thêm) · [`docs/HUONG_DAN_GOOGLE_FACEBOOK.md`](docs/HUONG_DAN_GOOGLE_FACEBOOK.md) · toàn bộ thay đổi: `docs/backend_thanh_vien_B.patch`.
> Thiết kế app thợ, thuật toán, thực nghiệm: thư mục `docs/` trong gói **app thợ** (`worker-app`).

### Chạy (Windows / macOS / Linux, chỉ cần Docker Desktop)
```bash
docker compose up -d --build      # lần đầu 5–10 phút; xong mở http://localhost:8000/docs
docker compose ps                 # db và api phải "healthy"
```
Sau đó chạy **app thợ** (gói `worker-app`, xem README trong đó): `docker compose up -d --build` ở thư mục `worker-app` → mở http://localhost:8082. App tự gọi API ở cổng 8000 của cùng máy.

Container `api` khi khởi động tự làm theo thứ tự:
1. `python -m db.migrate` — chạy các file `db/migrations/*.sql` chưa chạy (002 app thợ, 003 lưu vết kiểm tra an toàn điện, 004 bỏ bảng khung giờ làm việc, 005 chế độ ghép tự động hybrid; lưu ở bảng `schema_migrations`, chạy lại không sao).
2. Nếu `SEED_DEMO=true` (mặc định): `db.seed_dashboard` (danh mục điện + dữ liệu cho web admin), `db.seed_worker_locations`, `db.seed_demo` (tài khoản demo + **6 tuần lịch sử làm việc** cho thợ demo: đơn, đánh giá, thu nhập, ví, lịch hẹn, thông báo — chỉ tạo 1 lần).
3. `uvicorn` + **bộ điều phối ghép cặp** chạy nền (tắt bằng `DISPATCHER_ENABLED=false`).

Muốn làm mới toàn bộ dữ liệu demo (VD trước buổi bảo vệ, để "hôm nay" có số liệu): `docker compose down -v` rồi `docker compose up -d`.

Tài khoản demo (mật khẩu `12345678`):

| Tài khoản | Vai trò |
|---|---|
| `tho@thonhanh.vn` | Thợ đã duyệt (Trần Minh Đức) |
| `tho2@thonhanh.vn` | Thợ đã duyệt thứ 2 — demo 2 thợ tranh 1 đơn |
| `tho.moi@thonhanh.vn` | Thợ vừa gửi hồ sơ, chờ duyệt |
| `khach@thonhanh.vn` / `0912000001` | Khách hàng |
| `admin@thonhanh.vn` / `0900000000` | Quản trị |

### Script hữu ích
```bash
# Đóng vai khách để demo app thợ (tạo đơn gần thợ demo, duyệt báo giá, thanh toán, đánh giá)
docker compose exec api python -m scripts.demo_customer order
docker compose exec api python -m scripts.demo_customer quote <mã đơn>
docker compose exec api python -m scripts.demo_customer pay <mã đơn> --method cash
docker compose exec api python -m scripts.demo_customer review <mã đơn> --stars 5
docker compose exec api python -m scripts.demo_customer rush --count 12    # nhiều đơn cùng lúc

# Thợ ảo: bật N thợ seed, tự nhận đơn, di chuyển, làm xong, thu tiền (chạy thành container riêng)
docker compose --profile bots up -d          # dừng: docker compose --profile bots stop bots

# Thực nghiệm so sánh 2 chế độ ghép cặp (không cần DB) -> CSV + bảng + biểu đồ
docker compose exec api python -m scripts.benchmark_matching --out /app/media/thuc-nghiem
```

### Biến môi trường mới
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GOOGLE_WEB_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID` | trống | Bật đăng nhập Google (trống = app ẩn nút) |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | trống | Bật đăng nhập Facebook |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | trống | Gửi mã quên mật khẩu qua email. Trống + `DEBUG=true`: mã in ra log và hiện trên app (demo) |
| `PUBLIC_BASE_URL` | trống | Gốc URL ảnh tải lên (VD `http://192.168.1.10:8000`); trống = lấy theo request |
| `CORS_ORIGIN_REGEX` | IP LAN | Cho phép web mở từ máy khác trong mạng LAN |
| `DISPATCHER_ENABLED` | `true` | Bật bộ điều phối nền |
| `LOCATION_MAX_AGE_MINUTES` | `10` | Vị trí thợ cũ hơn mức này thì không được ghép |
| `DISPATCH_MAX_WAIT_MINUTES` | `15` | Đơn đặt ngay chờ quá lâu thì hệ thống hủy |
| `COMMISSION_RATE` | `0.15` | Hoa hồng nền tảng |
| `WITHDRAWAL_AUTO_APPROVE` | `true` | Tự duyệt rút tiền (demo) |
| `PUSH_ENABLED` | `false` | Gửi Expo Push (cần development build) |
| `BOT_COUNT`, `BOT_ACCEPT` | `8`, `0.85` | Số thợ ảo và xác suất nhận đơn (profile `bots`) |

### Kiểm thử
Test chạy trên 1 CSDL riêng (test có ghi dữ liệu, đừng dùng CSDL demo):
```bash
docker compose up -d db
docker compose exec db createdb -U thonhanh thonhanh_test
docker compose exec -T db psql -q -U thonhanh -d thonhanh_test < db/schema.sql

python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
export DATABASE_URL=postgresql+psycopg://thonhanh:thonhanh@localhost:5432/thonhanh_test   # Windows: set DATABASE_URL=...
python -m db.migrate
pytest -q          # 325 test: Hungarian vs vét cạn, luồng app thợ, luồng app khách (~30 giây)
```
