-- =====================================================================
-- 002_worker_app.sql — Thay đổi CSDL cho App Thợ + thuật toán ghép cặp
-- (Thành viên B). Viết theo kiểu chạy lại nhiều lần không lỗi (idempotent),
-- nên áp dụng được cho cả DB mới lẫn DB nhóm đang có dữ liệu.
-- Chạy tự động bởi: python -m db.migrate
-- =====================================================================

-- 1. Đăng ký bằng Email / Google / Facebook: số điện thoại không bắt buộc lúc tạo tài khoản
--    (thợ vẫn phải nhập SĐT trước khi gửi hồ sơ xét duyệt). UNIQUE vẫn giữ, NULL không tính trùng.
ALTER TABLE users ALTER COLUMN phone DROP NOT NULL;

-- 2. Mã đặt lại mật khẩu (quên mật khẩu qua email)
CREATE TABLE IF NOT EXISTS password_reset_codes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash VARCHAR(255) NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_codes(user_id);

-- 3. Hồ sơ thợ: thời điểm thợ bấm "Gửi hồ sơ xét duyệt"
ALTER TABLE worker_profiles ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP;

-- 4. Chỉ mục không gian GiST cho cột location
--    (geo_service.py ghi chú dùng idx_worker_profiles_location nhưng schema gốc chưa tạo)
CREATE INDEX IF NOT EXISTS idx_worker_profiles_location ON worker_profiles USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_worker_profiles_availability ON worker_profiles(availability);

-- 5. Lịch làm việc theo tuần (khung giờ rảnh). Thợ không khai báo = rảnh mọi lúc.
CREATE TABLE IF NOT EXISTS worker_schedules (
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),   -- 0 = Thứ 2 ... 6 = Chủ nhật
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (worker_id, weekday),
    CHECK (start_time < end_time)
);

-- 6. Tài khoản ngân hàng nhận tiền rút (mô phỏng)
CREATE TABLE IF NOT EXISTS worker_bank_accounts (
    worker_id BIGINT PRIMARY KEY REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    bank_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    account_holder VARCHAR(150) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 7. Ảnh trước / sau khi sửa (bằng chứng hoàn thành)
CREATE TABLE IF NOT EXISTS order_photos (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    uploader_id BIGINT NOT NULL REFERENCES users(id),
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('before', 'after')),
    url TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_photos_order ON order_photos(order_id);

-- 8. Lời mời nhận đơn (offer): hạn trả lời, đợt gửi, chế độ ghép, lý do từ chối/hủy.
--    Thêm trạng thái 'cancelled' = thợ đã nhận rồi nhưng hủy (dùng cho thống kê tỷ lệ hủy).
ALTER TABLE order_offers ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE order_offers ADD COLUMN IF NOT EXISTS round INT NOT NULL DEFAULT 1;
ALTER TABLE order_offers ADD COLUMN IF NOT EXISTS mode VARCHAR(20);
ALTER TABLE order_offers ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE order_offers DROP CONSTRAINT IF EXISTS order_offers_status_check;
ALTER TABLE order_offers ADD CONSTRAINT order_offers_status_check
    CHECK (status IN ('sent', 'accepted', 'rejected', 'expired', 'cancelled'));
CREATE INDEX IF NOT EXISTS idx_order_offers_worker_status ON order_offers(worker_id, status);
CREATE INDEX IF NOT EXISTS idx_order_offers_status_expires ON order_offers(status, expires_at);

-- 9. Báo giá phát sinh: thợ được rút lại báo giá khách chưa trả lời
ALTER TABLE order_extra_quotes DROP CONSTRAINT IF EXISTS order_extra_quotes_status_check;
ALTER TABLE order_extra_quotes ADD CONSTRAINT order_extra_quotes_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'));

-- 10. Hàng đợi điều phối: mỗi đơn đang tìm thợ có 1 dòng
CREATE TABLE IF NOT EXISTS order_dispatches (
    order_id BIGINT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('instant', 'batch')),
    rounds INT NOT NULL DEFAULT 0,             -- số đợt đã gửi offer
    offers_sent INT NOT NULL DEFAULT 0,
    last_candidates INT,                       -- số ứng viên hợp lệ ở lần ghép gần nhất
    next_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMP,
    deadline_at TIMESTAMP NOT NULL,            -- quá hạn mà chưa có thợ thì hệ thống hủy đơn
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_dispatches_next ON order_dispatches(next_attempt_at);

-- 11. Ví của thợ (sổ cái). Số dư = SUM(amount).
--     earning: +tiền thực nhận (khách trả online), commission: -hoa hồng (khách trả tiền mặt cho thợ)
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id BIGSERIAL PRIMARY KEY,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    type VARCHAR(30) NOT NULL
        CHECK (type IN ('earning', 'commission', 'withdrawal', 'withdrawal_refund', 'topup', 'adjustment')),
    amount NUMERIC(12,0) NOT NULL,
    order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,
    withdrawal_id BIGINT,
    description VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_worker ON wallet_transactions(worker_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_tx_order_type
    ON wallet_transactions(order_id, type) WHERE order_id IS NOT NULL;

-- 12. Yêu cầu rút tiền về ngân hàng (mô phỏng)
CREATE TABLE IF NOT EXISTS worker_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    amount NUMERIC(12,0) NOT NULL CHECK (amount > 0),
    bank_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    account_holder VARCHAR(150) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'rejected')),
    transaction_code VARCHAR(100),
    note TEXT,
    processed_by BIGINT REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_worker ON worker_withdrawals(worker_id, created_at DESC);

-- 13. Một số chỉ mục phục vụ các truy vấn của app thợ
CREATE INDEX IF NOT EXISTS idx_messages_order_unread ON messages(order_id, is_read);
CREATE INDEX IF NOT EXISTS idx_worker_earnings_worker ON worker_earnings(worker_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_worker_status ON orders(worker_id, status);
CREATE INDEX IF NOT EXISTS idx_order_history_order ON order_status_history(order_id);
