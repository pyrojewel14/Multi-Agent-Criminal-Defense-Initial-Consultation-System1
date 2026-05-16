from fastapi import APIRouter

from app.utils.logger import get_logger

_logger = get_logger("ConsultationAPI")

consultation_router = APIRouter(prefix="/consultation", tags=["consultation"])


@consultation_router.post("/chat")
async def chat():
    """Placeholder endpoint — will be replaced by the full consultation pipeline."""
    _logger.debug("Chat endpoint called (stub)")
    return {"message": "Chat with the consultation system"}
