from fastapi import APIRouter

consultation_router = APIRouter(prefix="/consultation", tags=["consultation"])

@consultation_router.post("/chat")
async def chat():
    return {"message": "Chat with the consultation system"}