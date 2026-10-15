import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.middleware.cors import setup_cors
from app.routes import api_router
from app.routes.upload_routes import media_root
from app.services.dispatcher import dispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Bộ điều phối ghép cặp chạy nền (gửi offer, hết hạn, ghép theo lô, hủy đơn quá hạn)
    if settings.dispatcher_enabled:
        dispatcher.start()
    yield
    if settings.dispatcher_enabled:
        dispatcher.stop()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

setup_cors(app)
app.include_router(api_router, prefix="/api/v1")
# Ảnh đã tải lên (giấy tờ, ảnh trước/sau, ảnh chat...)
app.mount(settings.media_url_prefix, StaticFiles(directory=media_root()), name="media")
