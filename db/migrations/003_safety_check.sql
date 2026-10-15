-- 003: Lưu vết xác nhận kiểm tra an toàn điện của thợ trước khi bắt đầu sửa (phục vụ tranh chấp / sự cố)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS safety_checked_at TIMESTAMP;
