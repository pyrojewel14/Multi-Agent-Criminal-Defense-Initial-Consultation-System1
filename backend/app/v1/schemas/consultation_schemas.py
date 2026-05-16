from pydantic import BaseModel
from typing import Optional


class ConsultationRequest(BaseModel):
    """Incoming message from client to an agent"""
    session_id: Optional[str] = None
    message: str
    user_type: Optional[str] = None  # suspect / victim / family


class ConsultationResponse(BaseModel):
    """Agent reply returned to the client"""
    session_id: str
    content: str
    disclaimer: str = "本内容为智能辅助生成，仅供参考，待律师确认后生效。"
    current_agent: str
    consent_required: bool = False


class ConfirmConsentRequest(BaseModel):
    """Client explicitly accepts or declines the privacy consent form"""
    consent_given: bool
