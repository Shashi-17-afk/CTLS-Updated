from fastapi import APIRouter
from backend.app.api.v1.endpoints import bookings, documents, health

api_v1_router = APIRouter()

api_v1_router.include_router(
    health.router,
    tags=["Health"],
)

api_v1_router.include_router(
    documents.router,
    prefix="/documents",
    tags=["Documents"],
)

api_v1_router.include_router(
    bookings.router,
    prefix="/bookings",
    tags=["Bookings"],
)
