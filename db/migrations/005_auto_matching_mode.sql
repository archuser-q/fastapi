-- 005 (Thành viên B): chế độ ghép cặp "auto" (hybrid, tự thích ứng theo mức tranh chấp thợ)
--   Mỗi nhịp điều phối: đơn không tranh thợ với đơn nào khác -> gửi ngay kiểu tức thời (top-k);
--   nhóm đơn tranh cùng thợ -> giải Hungarian để tối ưu toàn cục.
--   orders.matching_mode và order_offers.mode vẫn ghi chế độ THỰC TẾ đã dùng ('instant' | 'batch').
ALTER TABLE matching_configs DROP CONSTRAINT IF EXISTS matching_configs_mode_check;
ALTER TABLE matching_configs ADD CONSTRAINT matching_configs_mode_check CHECK (mode IN ('instant', 'batch', 'auto'));

ALTER TABLE order_dispatches DROP CONSTRAINT IF EXISTS order_dispatches_mode_check;
ALTER TABLE order_dispatches ADD CONSTRAINT order_dispatches_mode_check CHECK (mode IN ('instant', 'batch', 'auto'));
