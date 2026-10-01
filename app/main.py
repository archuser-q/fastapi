from fastapi import FastAPI

from app.config import settings
from app.middleware.cors import setup_cors
from app.routes import api_router

app = FastAPI(title=settings.app_name, debug=settings.debug)

setup_cors(app)
app.include_router(api_router, prefix="/api/v1")