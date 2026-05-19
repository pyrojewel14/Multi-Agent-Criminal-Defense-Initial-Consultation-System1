from fastapi import APIRouter
from app.v1.router.consultation import router as consultation_router
from app.v1.router.lawyer import router as lawyer_router

api_router = APIRouter()

api_router.include_router(consultation_router)
api_router.include_router(lawyer_router)

__all__ = ["api_router", "consultation_router", "lawyer_router"]