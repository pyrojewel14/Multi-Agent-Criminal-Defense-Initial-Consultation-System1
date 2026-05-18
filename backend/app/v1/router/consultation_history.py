from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_config import get_db
from app.models.user import User, UserRole, Consultation, ConsultationMessage, ConsultationStatus
from app.security.rbac import get_current_user, require_admin, require_lawyer
from app.core.success_response import success_response
from app.core.rate_limit import rate_limit
from app.utils.logger import get_logger
from app.v1.schemas.consultation_schemas import (
    ConsultationResponse,
    MessageResponse,
    ConsultationListResponse,
    AssignLawyerRequest,
    UpdateStatusRequest,
)

_logger = get_logger("ConsultationRouter")

consultation_router = APIRouter(prefix="/consultations", tags=["consultations"])


async def _build_consultation_response(
    consultation: Consultation,
    db: AsyncSession
) -> ConsultationResponse:
    client_result = await db.execute(select(User).where(User.id == consultation.client_id))
    client = client_result.scalar_one_or_none()
    
    lawyer_name = None
    if consultation.assigned_lawyer_id:
        lawyer_result = await db.execute(select(User).where(User.id == consultation.assigned_lawyer_id))
        lawyer = lawyer_result.scalar_one_or_none()
        lawyer_name = lawyer.real_name if lawyer else None
    
    return ConsultationResponse(
        id=consultation.id,
        client_id=consultation.client_id,
        client_username=client.username if client else None,
        client_real_name=client.real_name if client else None,
        assigned_lawyer_id=consultation.assigned_lawyer_id,
        assigned_lawyer_name=lawyer_name,
        user_type=consultation.user_type,
        consent_given=consultation.consent_given,
        status=consultation.status.value if consultation.status else None,
        facts_structured=consultation.facts_structured,
        applied_laws=consultation.applied_laws,
        final_output=consultation.final_output,
        created_at=consultation.created_at,
        updated_at=consultation.updated_at,
        completed_at=consultation.completed_at,
    )


@consultation_router.get("/list", response_model=ConsultationListResponse)
async def list_consultations(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取咨询列表，根据用户角色返回不同范围的咨询记录。
    
    - 超管(admin): 可查看所有咨询记录
    - 律师(lawyer): 可查看分配给自己的咨询记录
    - 客户(client): 可查看自己的咨询记录
    """
    offset = (page - 1) * page_size
    
    if current_user["role"] == "admin":
        query = select(Consultation)
        count_query = select(Consultation)
    elif current_user["role"] == "lawyer":
        query = select(Consultation).where(Consultation.assigned_lawyer_id == current_user["user_id"])
        count_query = select(Consultation).where(Consultation.assigned_lawyer_id == current_user["user_id"])
    else:
        query = select(Consultation).where(Consultation.client_id == current_user["user_id"])
        count_query = select(Consultation).where(Consultation.client_id == current_user["user_id"])
    
    if status:
        query = query.where(Consultation.status == ConsultationStatus(status))
        count_query = count_query.where(Consultation.status == ConsultationStatus(status))
    
    total_result = await db.execute(select(func.count()).select_from(count_query.subquery()))
    total = total_result.scalar_one()
    
    query = query.offset(offset).limit(page_size).order_by(Consultation.created_at.desc())
    result = await db.execute(query)
    consultations = result.scalars().all()
    
    response_list = []
    for c in consultations:
        response_list.append(await _build_consultation_response(c, db))
    
    return success_response(data=ConsultationListResponse(
        consultations=response_list,
        total=total,
        page=page,
        page_size=page_size,
    ))


@consultation_router.get("/{consultation_id}", response_model=ConsultationResponse)
async def get_consultation(
    consultation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取咨询详情，根据用户角色进行权限验证。"""
    result = await db.execute(select(Consultation).where(Consultation.id == consultation_id))
    consultation = result.scalar_one_or_none()
    
    if not consultation:
        raise HTTPException(status_code=404, detail="咨询记录不存在")
    
    if current_user["role"] == "client" and consultation.client_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此咨询记录")
    
    if current_user["role"] == "lawyer" and consultation.assigned_lawyer_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此咨询记录")
    
    return success_response(data=await _build_consultation_response(consultation, db))


@consultation_router.get("/{consultation_id}/messages")
async def get_consultation_messages(
    consultation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取咨询的所有消息记录。"""
    consultation_result = await db.execute(select(Consultation).where(Consultation.id == consultation_id))
    consultation = consultation_result.scalar_one_or_none()
    
    if not consultation:
        raise HTTPException(status_code=404, detail="咨询记录不存在")
    
    if current_user["role"] == "client" and consultation.client_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此咨询记录")
    
    if current_user["role"] == "lawyer" and consultation.assigned_lawyer_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此咨询记录")
    
    messages_result = await db.execute(
        select(ConsultationMessage)
        .where(ConsultationMessage.consultation_id == consultation_id)
        .order_by(ConsultationMessage.created_at)
    )
    messages = messages_result.scalars().all()
    
    return success_response(data=[MessageResponse.model_validate(m) for m in messages])


@consultation_router.post("/assign")
async def assign_lawyer(
    request: AssignLawyerRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """超管将咨询分配给律师。

    Args:
        consultation_id: 咨询记录ID
        lawyer_id: 律师ID
    """
    consultation_id = request.consultation_id
    lawyer_id = request.lawyer_id

    lawyer_result = await db.execute(
        select(User).where(User.id == lawyer_id, User.role == UserRole.LAWYER)
    )
    lawyer = lawyer_result.scalar_one_or_none()

    if not lawyer:
        raise HTTPException(status_code=404, detail="律师不存在")

    consultation_result = await db.execute(select(Consultation).where(Consultation.id == consultation_id))
    consultation = consultation_result.scalar_one_or_none()

    if not consultation:
        raise HTTPException(status_code=404, detail="咨询记录不存在")

    consultation.assigned_lawyer_id = lawyer_id
    await db.commit()

    _logger.info("咨询分配律师: consultation_id=%s, lawyer_id=%s", consultation_id, lawyer_id)

    return success_response(message=f"已将咨询分配给律师 {lawyer.real_name}")


@consultation_router.put("/{consultation_id}/status")
async def update_consultation_status(
    consultation_id: str,
    request: UpdateStatusRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新咨询状态。律师和超管可以更新状态。"""
    if current_user["role"] == "client":
        raise HTTPException(status_code=403, detail="客户无权修改咨询状态")
    
    result = await db.execute(select(Consultation).where(Consultation.id == consultation_id))
    consultation = result.scalar_one_or_none()
    
    if not consultation:
        raise HTTPException(status_code=404, detail="咨询记录不存在")
    
    if current_user["role"] == "lawyer" and consultation.assigned_lawyer_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="只能修改分配给自己的咨询状态")
    
    try:
        new_status = ConsultationStatus(request.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的状态值")
    
    consultation.status = new_status
    
    if new_status == ConsultationStatus.COMPLETED:
        consultation.completed_at = datetime.utcnow()
    
    await db.commit()
    
    _logger.info("咨询状态更新: consultation_id=%s, new_status=%s", consultation_id, request.status)
    
    return success_response(message=f"咨询状态已更新为 {request.status}")