"""Cấu hình chung cho test: tắt bộ điều phối chạy nền (test tự gọi từng bước), ảnh lưu vào thư mục tạm."""

import os
import tempfile

os.environ.setdefault("DISPATCHER_ENABLED", "false")
os.environ.setdefault("PUSH_ENABLED", "false")
os.environ.setdefault("MEDIA_DIR", os.path.join(tempfile.gettempdir(), "thonhanh-test-media"))
os.environ.setdefault("WITHDRAWAL_AUTO_APPROVE", "true")
os.environ.setdefault("DEBUG", "true")
