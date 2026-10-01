from fastapi import APIRouter

from app.routes import admin_routes, auth_routes, health_routes

api_router = APIRouter()
api_router.include_router(health_routes.router)
api_router.include_router(auth_routes.router)
api_router.include_router(admin_routes.router)