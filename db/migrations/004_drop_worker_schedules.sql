-- 004: Bỏ khung giờ làm việc theo tuần của thợ.
-- Thợ chỉ cần bật/tắt nhận đơn; với đơn hẹn trước, lời mời ghi rõ giờ hẹn để thợ tự quyết nhận hay không,
-- hệ thống chỉ chặn thợ đã có lịch hẹn trùng giờ (xem dispatch_service.filter_eligible).
DROP TABLE IF EXISTS worker_schedules;
