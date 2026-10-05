from fastapi import APIRouter

from app.routes import (
    admin_routes,
    auth_routes,
    catalog_admin_routes,
    complaint_admin_routes,
    dashboard_routes,
    health_routes,
    matching_admin_routes,
    order_admin_routes,
    review_admin_routes,
    worker_app_routes,
)

api_router = APIRouter()
api_router.include_router(health_routes.router)
api_router.include_router(auth_routes.router)
api_router.include_router(admin_routes.router)
api_router.include_router(dashboard_routes.router)
api_router.include_router(order_admin_routes.router)
api_router.include_router(complaint_admin_routes.router)
api_router.include_router(review_admin_routes.router)
api_router.include_router(catalog_admin_routes.router)
api_router.include_router(matching_admin_routes.router)
api_router.include_router(worker_app_routes.router)