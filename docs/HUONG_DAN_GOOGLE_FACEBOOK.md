# Bật đăng nhập Google và Facebook

App thợ đã có sẵn nút "Tiếp tục với Google / Facebook". Nút chỉ hoạt động khi nhóm **đăng ký ứng dụng** với Google và Meta (miễn phí) rồi điền mã vào file `.env` của backend. Không app nào tự đăng nhập Google/Facebook được nếu chưa đăng ký mã này — đây là quy định của Google/Meta, không phải lỗi của code.

Cách hoạt động: app lấy token từ Google/Facebook → gửi cho backend → **backend tự kiểm tra lại token với Google/Facebook** (không tin dữ liệu app gửi lên) → tạo tài khoản hoặc đăng nhập (trùng email với tài khoản có sẵn thì tự liên kết).

> Phạm vi hướng dẫn: bản **web** của app thợ mở ở `http://localhost:8082` (cách demo dễ nhất). Trên điện thoại thì cần bản APK build riêng (development build), vì app Expo Go không nhận lại kết quả đăng nhập của Google/Facebook — xem mục cuối.

---

## 1. Google (khoảng 10 phút)

1. Vào https://console.cloud.google.com, đăng nhập Gmail của nhóm. Góc trên chọn **Select a project → New project**, đặt tên VD `tho-nhanh`, bấm **Create**.
2. Mở menu ☰ → **APIs & Services → OAuth consent screen** (giao diện mới tên là **Google Auth Platform**). Bấm **Get started** và điền:
   - **App name**: `Thợ Nhanh`, **User support email**: email của bạn.
   - **Audience**: chọn **External**.
   - **Contact information**: email của bạn → đồng ý điều khoản → **Create**.
3. Trong **Google Auth Platform → Audience**, ở mục **Test users** bấm **Add users**, thêm các Gmail sẽ dùng để demo (app ở trạng thái *Testing* thì chỉ những tài khoản này đăng nhập được — đủ cho đồ án).
4. Vào **Google Auth Platform → Clients → Create client**:
   - **Application type**: **Web application**, tên tuỳ ý.
   - **Authorized JavaScript origins**: thêm `http://localhost:8082` (và `http://localhost:8081` nếu chạy bằng `npx expo start --web`).
   - **Authorized redirect URIs**: thêm `http://localhost:8082` và `http://localhost:8082/` (tương tự với 8081 nếu dùng).
   - Bấm **Create**, chép **Client ID** (dạng `xxxx.apps.googleusercontent.com`). App thợ dùng luồng lấy *ID token* trên trình duyệt nên **không cần Client secret**.
5. Mở file `.env` trong thư mục `backend` (chưa có thì `copy .env.example .env`), điền:
   ```
   GOOGLE_WEB_CLIENT_ID=xxxx.apps.googleusercontent.com
   ```
6. Khởi động lại API: `docker compose up -d` (trong thư mục `backend`). Không cần build lại app.
7. Mở `http://localhost:8082` → **Tiếp tục với Google** → chọn Gmail đã thêm ở bước 3.

Lưu ý của Google:
- Chỉ chấp nhận `http` với **localhost**; mở web bằng IP LAN (VD `http://192.168.1.10:8082`) sẽ báo `origin_mismatch`. Muốn dùng trên máy khác thì phải có tên miền **https**.
- Sửa cấu hình xong có thể mất **5 phút đến vài giờ** mới có hiệu lực.

## 2. Facebook (khoảng 10 phút)

1. Vào https://developers.facebook.com, đăng nhập Facebook, bấm **My Apps → Create app**.
2. Chọn use case **Authenticate and request data from users with Facebook Login**, đặt tên app `Thợ Nhanh`, email liên hệ → **Create app**.
3. Ở menu trái **Use cases → Facebook Login → Customize**:
   - Mục **Permissions**: bấm **Add** cho `email` (`public_profile` có sẵn).
   - Mục **Settings**: ô **Valid OAuth Redirect URIs** thêm `http://localhost:8082/` → **Save changes**.
4. Menu trái **App settings → Basic**: chép **App ID** và bấm **Show** để chép **App secret**.
5. Điền vào `backend/.env`:
   ```
   FACEBOOK_APP_ID=1234567890
   FACEBOOK_APP_SECRET=abcdef...
   ```
   rồi `docker compose up -d` để API nhận cấu hình.
6. App đang ở chế độ **Development**: chỉ tài khoản có vai trò trong app đăng nhập được. Thêm người demo ở **App roles → Roles → Add People** (vai trò Tester), người đó chấp nhận lời mời trên Facebook.

`App secret` chỉ để ở backend (`.env`), **không** đưa vào app hay đẩy lên GitHub (`.env` đã nằm trong `.gitignore`).

## 3. Kiểm tra nhanh

- Mở `http://localhost:8000/api/v1/auth/providers`: thấy `google.web_client_id` và `facebook.app_id` khác `null` là backend đã nhận cấu hình.
- Nút trên app sáng (không còn mờ). Bấm vào mà vẫn báo "chưa cấu hình" thì tải lại trang (`Ctrl + F5`).
- Lỗi thường gặp:

| Hiện tượng | Nguyên nhân |
|---|---|
| `origin_mismatch` / `redirect_uri_mismatch` (Google) | Thiếu `http://localhost:8082` trong 2 danh sách ở bước 1.4, hoặc đang mở web bằng IP thay vì localhost |
| `Access blocked: app has not completed verification` | Gmail chưa được thêm vào **Test users** |
| "URL Blocked" (Facebook) | Thiếu `http://localhost:8082/` trong Valid OAuth Redirect URIs |
| Facebook báo app chưa sẵn sàng | Tài khoản chưa được thêm làm Tester, hoặc chưa chấp nhận lời mời |
| Đăng nhập xong báo lỗi xác minh token | Container API không ra được Internet (cần gọi `oauth2.googleapis.com` / `graph.facebook.com`) |

## 4. Trên điện thoại (khi cần)

Expo Go không dùng được 2 nút này. Muốn chạy trên điện thoại cần build APK (development build bằng EAS, xem `worker-app/README.md`) và tạo thêm:
- Google: client loại **Android** (package `vn.thonhanh.worker` + mã SHA-1 của chứng chỉ ký) → `GOOGLE_ANDROID_CLIENT_ID`; iOS tương tự với bundle `vn.thonhanh.worker` → `GOOGLE_IOS_CLIENT_ID`.
- Facebook: thêm nền tảng Android/iOS trong **App settings → Basic → Add platform**.

Với buổi bảo vệ, khuyên dùng bản web để demo đăng nhập mạng xã hội; trên điện thoại dùng tài khoản email.
