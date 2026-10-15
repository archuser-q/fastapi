#!/bin/sh
# Khởi động API: cập nhật CSDL -> (tuỳ chọn) nạp dữ liệu demo -> chạy server
set -e

python -m db.migrate

if [ "${SEED_DEMO:-true}" = "true" ]; then
  python -m db.seed_dashboard
  python -m db.seed_worker_locations
  python -m db.seed_demo
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ${UVICORN_ARGS:-}
