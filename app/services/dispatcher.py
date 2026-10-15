"""Tiến trình nền chạy bộ điều phối theo nhịp (tick) vài giây một lần.

Mỗi tick:
  1. Cho hết hạn các offer quá thời gian trả lời
  2. Chế độ tức thời: gửi đợt offer tiếp theo cho các đơn tới lượt
  3. Chế độ theo lô: đủ batch_window_seconds thì chạy 1 lượt Hungarian
     Chế độ auto (hybrid): mỗi tick chia đơn đang chờ theo nhóm tranh chấp thợ (tức thời / Hungarian)
  4. Hủy đơn quá hạn chờ, nhắc thợ trước giờ hẹn

Chỉ 1 tiến trình được làm "leader" (giữ khóa advisory phiên của PostgreSQL), nên chạy
uvicorn nhiều worker hay nhiều container API cũng không bị gửi offer trùng.
"""

import logging
import threading
import time

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.services import dispatch_service
from app.services.matching_service import load_active_config

log = logging.getLogger("thonhanh.dispatcher")
LEADER_KEY = 815_000
REMINDER_EVERY_SECONDS = 30


class Dispatcher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._leader_conn = None
        self._last_batch = 0.0
        self._last_reminder = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._release()

    def _release(self) -> None:
        if self._leader_conn is not None:
            try:
                self._leader_conn.close()
            except Exception:
                pass
            self._leader_conn = None

    def _is_leader(self) -> bool:
        if self._leader_conn is not None:
            return True
        conn = engine.connect()
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_KEY}).scalar()
        conn.commit()
        if got:
            self._leader_conn = conn
            log.info("Bộ điều phối bắt đầu chạy (leader)")
            return True
        conn.close()
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._is_leader():
                    self.tick()
                else:
                    self._stop.wait(5)
                    continue
            except Exception:
                log.exception("Lỗi trong tick điều phối")
                self._release()
            self._stop.wait(settings.dispatcher_tick_seconds)

    def tick(self) -> None:
        with SessionLocal() as db:
            dispatch_service.expire_offers(db)
            dispatch_service.run_due_instant(db)
            cfg = load_active_config(db)
            # auto (hybrid): xét mỗi nhịp — đơn lẻ gửi ngay, nhóm đơn tranh cùng thợ giải Hungarian
            dispatch_service.run_auto_round(db, cfg)
            now = time.monotonic()
            if now - self._last_batch >= cfg.batch_window_seconds:
                self._last_batch = now
                dispatch_service.run_batch_round(db, cfg)
            dispatch_service.cancel_overdue(db)
            if now - self._last_reminder >= REMINDER_EVERY_SECONDS:
                self._last_reminder = now
                dispatch_service.send_schedule_reminders(db)


dispatcher = Dispatcher()
