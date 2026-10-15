# Hướng dẫn tích hợp cho cả nhóm

Phần của thành viên B gồm 2 gói: **backend** (sửa trên nhánh `fastapi-feature-customer-app`, gói `tho-nhanh-backend.zip`) và **app thợ** (`worker-app/`, gói `tho-nhanh-app-tho.zip`, kèm tài liệu thiết kế trong `worker-app/docs/`). Tài liệu này nói rõ đã đụng vào file nào của các bạn, cái gì tương thích ngược, và mỗi bạn cần làm thêm gì.

## 1. Gộp code

### Backend
Backend ở đây = nhánh `fastapi-feature-customer-app` của nhóm + các commit của B. Có 2 cách:

```bash
# Cách 1 (khuyên dùng): áp patch lên repo backend của nhóm, đứng ở nhánh feature
git checkout fastapi-feature-customer-app        # nhánh gốc mà B đã làm tiếp
git apply --3way /đường/dẫn/backend/docs/backend_thanh_vien_B.patch
git add -A && git commit -m "App thợ: auth email/Google/Facebook, điều phối ghép cặp, API app thợ"

# Cách 2: chép đè cả thư mục backend/ (nếu nhánh của nhóm chưa có commit mới nào khác)
```

Sau khi gộp, khởi động lại bằng Docker là đủ: container API tự chạy migration `002_worker_app.sql`, `003_safety_check.sql`, `004_drop_worker_schedules.sql`, `005_auto_matching_mode.sql` (idempotent, chạy lại không sao) rồi nạp dữ liệu demo. **Không cần xoá volume DB.**

### App thợ
Thư mục `worker-app/` độc lập (Expo). Đặt cạnh `customer-app/` và `dashboard/` trong repo React, hoặc làm repo riêng.

### Chạy
Mỗi gói có `docker-compose.yml` riêng: `backend/` chạy db + api (+ thợ ảo với `--profile bots`), `worker-app/` chạy bản web app thợ ở cổng 8082 và tự gọi API cổng 8000 cùng máy. Web quản trị và app khách của nhóm cũng gọi vào cùng API này.

## 2. File của các bạn mà B đã sửa

Chỉ sửa ở mức tối thiểu, mỗi chỗ đều có comment giải thích trong code.

| File | Sửa gì | Vì sao |
|---|---|---|
| `app/config.py` | Thêm cấu hình mới (Google/Facebook, SMTP, upload, điều phối, ví…); `extra="ignore"` | `.env.example` cũ có `POSTGRES_*` làm `Settings` báo lỗi *extra_forbidden* khi chạy ngoài Docker |
| `app/database.py` | Đặt `timezone=Asia/Ho_Chi_Minh` cho mọi kết nối | **Lỗi cũ**: DB trong Docker chạy UTC, cột mặc định `NOW()` lệch 7 tiếng so với `now_vn()` của code (VD đơn mới tạo đã "quá hạn") |
| `app/main.py` | Khởi động bộ điều phối nền (lifespan); phục vụ ảnh tại `/media` | |
| `app/middleware/cors.py` | Thêm `allow_origin_regex` | Mở web/app từ IP LAN (điện thoại cùng Wi-Fi) |
| `app/models/user.py` | `phone` cho phép NULL | Đăng ký bằng email/Google/Facebook |
| `app/models/order.py`, `worker.py` | Thêm cột mới của `order_offers`, `orders.safety_checked_at`, `worker_profiles.submitted_at` | Vòng đời offer, lưu vết kiểm tra an toàn điện, thời điểm gửi hồ sơ |
| `app/models/__init__.py`, `app/routes/__init__.py` | Đăng ký model/route mới | |
| `app/schemas/{geo,review_admin,complaint_admin,order_admin,matching,customer,user}.py` | `phone: str \| None` | Do `users.phone` có thể NULL — nếu không, API admin/khách lỗi 500 khi gặp user đăng ký bằng email |
| `app/schemas/auth.py`, `app/controllers/auth_controller.py`, `app/routes/auth_routes.py` | Viết lại: đăng nhập bằng email **hoặc** SĐT, kiểm tra vai trò theo app, Google, Facebook, quên/đặt lại mật khẩu | Nhóm chốt bỏ SMS OTP. **Vẫn nhận `{phone, password}`** như cũ → app khách & web admin hiện tại không phải sửa |
| `app/routes/worker_app_routes.py` | Từ 1 endpoint `/worker/location` → toàn bộ API app thợ | `PATCH /worker/location` giữ nguyên đường dẫn, thêm ghi lịch sử vị trí |
| `app/services/matching_service.py` | Tách thành lọc → ràng buộc → chấm điểm; điểm dùng chung module `app/matching/scoring.py` | Trang **mô phỏng** của web admin vẫn chạy như cũ (`rank_workers` giữ nguyên đầu ra) |
| `app/services/notification_service.py` | Thêm gửi Expo Push sau khi commit (tắt mặc định) | |
| `app/controllers/customer_order_controller.py` | Thay comment `MATCHING_HOOK` bằng lời gọi `dispatch_service.start_dispatch`; khi khách hủy thì cập nhật trạng thái rảnh của thợ; định dạng tiền trong thông báo | Đơn mới được đưa vào bộ điều phối |
| `app/controllers/customer_payment_controller.py` | Sau khi thanh toán sandbox thành công → `record_paid_order` (ghi thu nhập + cộng ví thợ); định dạng tiền `350.000đ` thay vì `350,000đ` | |
| `app/controllers/admin_controller.py` | Gửi thông báo cho thợ khi admin từ chối giấy tờ / duyệt hồ sơ / duyệt ảnh giấy tờ cập nhật | |
| `app/schemas/matching.py` | `mode` nhận thêm `"auto"` (hybrid); auto không dùng `batch_window_seconds` | Chế độ ghép tự động (mục 3.13) |
| `db/seed_dashboard.py` (= `scripts/seed_dashboard.py`) | Danh mục chỉ còn **điện** (4 nhóm, 11 dịch vụ); **thêm `worker_services` cho thợ seed**; admin có email | **Lỗi cũ**: thợ seed không có kỹ năng nào nên thuật toán ghép không tìm được ai |
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`, `.gitignore` | Entry-point chạy migration + seed; mọi biến có mặc định; volume ảnh | "`docker compose up` là chạy" |

File **mới** (không đụng ai): `app/matching/*`, `app/services/{dispatch_service,dispatcher,worker_service,social_auth,email_service}.py`, `app/controllers/worker_*`, `app/models/worker_app.py`, `app/schemas/worker_app.py`, `app/routes/{upload,order_photo,withdrawal_admin}_routes.py`, `db/migrate.py`, `db/migrations/00{2,3,4}_*.sql`, `db/seed_demo.py`, `db/seed_media.py` + `db/seed_assets/*.png` (ảnh mẫu), `scripts/{worker_bots,demo_customer,benchmark_matching}.py`, `tests/*` (mới: `conftest.py`, `test_hungarian.py`, `test_worker_flow.py`).

Danh sách đầy đủ từng dòng: `docs/backend_thanh_vien_B.patch`.

## 3. Thay đổi hành vi cần biết

0a. **Đơn hẹn trước chỉ được bắt đầu di chuyển trong 60 phút trước giờ hẹn** (sớm hơn → 400; chi tiết đơn có `start_available_at`). **Báo giá phát sinh chỉ sau khi thợ đã đến nơi** (`arrived` / `in_progress`). App khách không phải sửa gì, chỉ là báo giá sẽ không xuất hiện khi thợ đang trên đường.
0b. **Bỏ khung giờ làm việc của thợ**: xoá `GET/PUT /worker/schedule` và bảng `worker_schedules` (migration 004). Đơn hẹn trước mời thợ đang bật nhận đơn, lời mời ghi rõ giờ hẹn, hệ thống chỉ chặn thợ đã có lịch trùng giờ (±120 phút). `GET /worker/home` không còn trường `demand` (bản đồ nhiệt).
0. **Bắt đầu sửa phải xác nhận an toàn điện**: `POST /worker/orders/{id}/status` với `status=in_progress` cần thêm `"safety_confirmed": true` (app thợ gửi khi thợ tick đủ checklist), server lưu `orders.safety_checked_at`. Web admin có thể hiển thị cột này ở chi tiết đơn ("Thợ xác nhận an toàn điện lúc …").

1. **Chế độ ghép do admin quyết định.** App khách vẫn gửi `matching_mode` nhưng server ghi đè bằng chế độ của cấu hình matching đang `is_active` (web admin → Cấu hình matching). Đổi cấu hình có hiệu lực ở nhịp điều phối kế tiếp (≤ 2 giây), không cần khởi động lại.
2. **Đơn không có thợ nhận sẽ tự hủy**: đặt ngay sau 15 phút (`DISPATCH_MAX_WAIT_MINUTES`), đơn hẹn trước giờ hẹn 15 phút. Khách nhận thông báo "Chưa tìm được thợ".
3. **Thợ hủy trước khi đến nơi** → đơn quay về `pending` và hệ thống tìm thợ khác (app khách nên hiện lại màn "đang tìm thợ" khi `status` trở về `pending`).
4. Trạng thái offer: `sent`, `accepted`, `rejected`, `expired` (hết giờ, thợ tắt nhận đơn, đã có thợ khác nhận hoặc đơn bị hủy), `cancelled` (thợ hủy sau khi đã nhận).
5. Trạng thái đơn `matched` **không dùng**.
6. **Ảnh mẫu là PNG** (`/media/seed/*.png`): app React Native không hiển thị được SVG. CSDL seed bằng bản cũ (`.svg`) tự được đổi sang `.png` khi API khởi động lại.
7. **URL ảnh lưu kèm địa chỉ lúc tải lên** (VD `http://localhost:8000/media/...`) nên điện thoại không mở được. App thợ tự đổi phần máy chủ của ảnh `/media/...` trên địa chỉ nội bộ (localhost, 192.168.x…) sang máy chủ API đang dùng — app khách nên làm tương tự (chép hàm `mediaUri` trong `worker-app/src/config/env.ts`).
8. Tài khoản admin seed: `admin@thonhanh.vn` hoặc `0900000000`, mật khẩu `12345678` (đăng nhập web admin bằng SĐT như cũ vẫn được).
9. **Cập nhật giấy tờ sau khi đã duyệt**: thợ gửi ảnh CCCD/chân dung mới → tạo bản `pending` riêng, bản `approved` cũ **vẫn giữ** (hồ sơ vẫn approved, thợ vẫn nhận việc). Admin duyệt bản mới như mọi giấy tờ (`PATCH /admin/worker-documents/{id}/review`), thợ nhận thông báo "Đã duyệt giấy tờ mới"; bản cũ giữ làm lịch sử (danh sách giấy tờ đã sắp mới → cũ). Thợ không gỡ được CCCD/chân dung đã duyệt (400), gỡ được bản chờ duyệt và chứng chỉ (kể cả đã duyệt). Web quản trị nên hiện giấy tờ chờ duyệt của cả thợ **đã duyệt** (không chỉ hồ sơ mới).
10. **Thợ khiếu nại đánh giá**: app thợ gửi báo cáo của đơn với lý do `[Thợ báo cáo] Đánh giá không đúng sự thật` (bảng `complaints`, như các báo cáo khác). Trang chi tiết đánh giá của web admin đã liệt kê khiếu nại của đơn đó (`complaints` trong `GET /admin/reviews/{id}`) nên admin xem ngay cạnh đánh giá rồi ẩn / giữ đánh giá. Thợ **không trả lời công khai** đánh giá (khách đặt thợ do hệ thống ghép, không chọn thợ theo đánh giá như sàn thương mại).
11. **Ảnh tải lên từ app thợ được thu nhỏ** (cạnh dài ≤ 1600 px, JPEG ~0,7) trước khi gửi `POST /uploads`, nên không vượt giới hạn 8 MB. App khách (Expo SDK 54+) nên gửi ảnh bằng `XMLHttpRequest` như `worker-app/src/api/client.ts` → `uploadImage`: `fetch` của Expo SDK mới không gửi được tệp dạng `{ uri }` trong `FormData`.
12. **Báo giá phát sinh nhiều mục**: API không đổi (`description`, `amount`), nhưng app thợ gửi nội dung dạng `Tên mục x2: 190.000đ; Tên mục khác: 50.000đ` (mục trong bảng giá chung có giá cố định, mục ngoài bảng giá do thợ nhập). App khách hiện nguyên chuỗi cũng đọc được; muốn đẹp hơn thì tách theo `"; "` rồi theo `": "` cuối cùng thành từng dòng (xem `quoteItems` trong `worker-app/src/screens/jobs/JobDetailScreen.tsx`). Khi demo chưa có app khách: `docker compose exec api python -m scripts.demo_customer quote <mã đơn>` để khách duyệt.
13. **Chế độ ghép `auto` (hybrid) — mặc định mới** (migration 005): mỗi nhịp điều phối, đơn không tranh thợ với ai → gửi tức thời top-k; nhóm đơn tranh cùng thợ → Hungarian. `orders.matching_mode` / `order_offers.mode` vẫn chỉ là `instant` | `batch` (chế độ **thực tế** đã dùng). Seed tạo 1 lần cấu hình "Tự động (hybrid)" và đặt làm cấu hình đang áp dụng. **Web quản trị** (trang Cấu hình matching) cần thêm lựa chọn `auto` ("Tự động") vào ô chọn chế độ; `POST/PUT /admin/matching/configs` đã nhận `mode: "auto"` (không cần `batch_window_seconds`).
14. **Danh sách đơn của thợ** (`GET /worker/orders`) có thêm `rating` (số sao khách đánh giá, đánh giá bị admin ẩn thì không hiện).
15. Lịch hẹn mẫu của seed ("Lắp quạt trần…") đã quá giờ mà chưa làm sẽ được **dời sang 9:30 sáng ngày làm việc kế tiếp** mỗi lần API khởi động, để thợ demo không bị kẹt trạng thái bận.

## 4. Việc cần làm thêm

### App khách hàng
- [ ] Đăng nhập/đăng ký bằng **email** (gửi `identifier` hoặc `email`), thêm nút Google/Facebook: `GET /auth/providers` để biết bật nút nào → `POST /auth/google` (`id_token` hoặc `access_token`) / `POST /auth/facebook` (`access_token`), luôn kèm `"role": "customer"`. Có thể chép `worker-app/src/auth/SocialButtons.tsx` (đổi `role`).
- [ ] Quên mật khẩu: `POST /auth/forgot-password {email}` → `POST /auth/reset-password {email, code, new_password}`.
- [ ] **Hỏi số điện thoại liên hệ trước lần đặt đơn đầu** (tài khoản Google/email có thể chưa có SĐT → thợ không gọi được). Backend cần thêm `phone` vào `ProfileUpdate` (`app/schemas/customer.py`) + kiểm tra trùng — việc nhỏ, bạn phụ trách app khách làm cùng để thống nhất UI.
- [ ] Hiện ảnh trước/sau của thợ: `GET /orders/{id}/photos` (danh sách `{id, kind: before|after, url, created_at}`).
- [ ] Màn theo dõi: khi đơn bị hệ thống hủy hoặc quay về `pending` (thợ hủy) thì hiện thông báo phù hợp.
- [ ] Bỏ lựa chọn "chế độ ghép" phía khách nếu có trên UI.

### Web quản trị
- [ ] (Tuỳ chọn) Chi tiết đơn: hiện `safety_checked_at` — mốc thợ xác nhận đã kiểm tra an toàn điện.
- [ ] Trang **Yêu cầu rút tiền**: `GET /admin/withdrawals?status=pending|completed|rejected`, `POST /admin/withdrawals/{id}/approve {transaction_code?, note?}`, `POST /admin/withdrawals/{id}/reject {note}`. (Bản demo đang tự duyệt: đặt `WITHDRAWAL_AUTO_APPROVE=false` để admin duyệt tay.)
- [ ] Các kiểu `phone: string` trong `src/types/*.ts` → `string | null`.
- [ ] (Tuỳ chọn) Trang giám sát đơn: hiển thị danh sách offer của đơn (đợt, chế độ, điểm, trạng thái) để minh hoạ thuật toán khi bảo vệ.

### Thành viên A (Trust Score)
- [ ] Cắm thuật toán vào `TRUST_SCORE_HOOK` (`customer_support_controller.create_review`). Hàm điểm ghép cặp đọc `worker_profiles.trust_score` (0..1) nên **không cần sửa gì bên ghép cặp**.

### Thành viên C (Geospatial)
- [ ] Migration 002 đã thêm index GiST `worker_profiles(location)` (schema cũ thiếu) — nên đo lại benchmark.
- [ ] Bộ điều phối gọi `geo_service.find_nearby_workers(db, lat, lng, radius_km, service_id=…, statuses=…, fresh_after=…, limit=…)` của C (không sửa file của C). Nếu C thay bằng lưới ô tự cài đặt thì giữ nguyên chữ ký hàm này là bộ điều phối dùng được ngay.

### Dọn repo
- [ ] Xoá file PDF hồ sơ cá nhân trong `dashboard/src/components/matching/` (cả nhánh main và feature) và khỏi lịch sử git trước khi nộp.
