from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ConsultationCreateRequest(BaseModel):
    user_type: str = Field(..., description="用户类型: suspect, victim, family")


class ConsultationUpdateRequest(BaseModel):
    user_type: Optional[str] = None
    consent_given: Optional[bool] = None
    facts_structured: Optional[str] = None
    applied_laws: Optional[str] = None
    final_output: Optional[str] = None


class MessageCreateRequest(BaseModel):
    content: str = Field(..., description="消息内容")
    sender_type: str = Field(..., description="发送者类型: user, agent, lawyer")
    sender_id: Optional[str] = None
    agent_name: Optional[str] = None
    message_type: str = "text"


class ConsultationResponse(BaseModel):
    id: str
    client_id: str
    client_username: Optional[str] = None
    client_real_name: Optional[str] = None
    assigned_lawyer_id: Optional[str] = None
    assigned_lawyer_name: Optional[str] = None
    user_type: str
    consent_given: bool
    status: str
    facts_structured: Optional[str] = None
    applied_laws: Optional[str] = None
    final_output: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: str
    consultation_id: str
    sender_type: str
    sender_id: Optional[str] = None
    content: str
    agent_name: Optional[str] = None
    message_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConsultationListResponse(BaseModel):
    consultations: List[ConsultationResponse]
    total: int
    page: int
    page_size: int


class AssignLawyerRequest(BaseModel):
    consultation_id: str = Field(..., description="咨询记录ID")
    lawyer_id: str = Field(..., description="律师ID")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="状态: pending, in_progress, completed, cancelled")