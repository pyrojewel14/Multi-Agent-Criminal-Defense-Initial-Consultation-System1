import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.db.redis_config import get_redis_cache_json, set_redis_cache
from app.errors.exceptions import ConsentRequiredException, HighRiskAlertException
from app.models.user import Consultation, ConsultationMessage, ConsultationStatus, User
from app.orchestrator.workflow import orchestrator
from app.security.disclaimer import disclaimer
from app.security.rbac import get_current_user
from app.state.consultation_state import ConsultationState
from app.utils.logger import get_logger
from app.v1.schemas.consultation_schemas import (
    ConfirmConsentRequest,
    ConfirmConsentResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    LawyerReviewRequest,
    LawyerReviewResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionCloseRequest,
    SessionCloseResponse,
    SessionListItem,
    SessionListResponse,
    SessionStateResponse,
    WebSocketMessage,
)

_logger = get_logger("Router.Consultation")

router = APIRouter(prefix="/api/v1/sessions", tags=["consultation"])


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """建立 WebSocket 连接"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        _logger.info("【connect】WebSocket连接建立: session_id=%s", session_id)

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """断开 WebSocket 连接"""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        _logger.info("【disconnect】WebSocket连接断开: session_id=%s", session_id)

    async def send_to_client(self, websocket: WebSocket, message: dict) -> None:
        """向客户端发送消息"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            _logger.error("【send_to_client】发送消息失败: %s", e)

    async def broadcast(self, session_id: str, message: dict) -> None:
        """广播消息到指定会话的所有连接"""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    _logger.error("【broadcast】广播消息失败: %s", e)


manager = ConnectionManager()

SESSION_TTL = 7200

HIGH_RISK_ALERT_MESSAGE = "为保护您的权益，此部分内容建议直接与律师单独沟通"


async def _handle_high_risk_alert(
    session_id: str,
    result: ConsultationState,
    current_agent: str,
) -> None:
    """Handle high-risk alert consistently across HTTP and WebSocket channels.

    Persists the alert state to orchestrator and Redis, ensuring the
    alert_triggered flag and conversation history are recorded regardless
    of which transport channel triggered the alert.

    Args:
        session_id: Session identifier.
        result: Updated ConsultationState with alert_triggered=True.
        current_agent: Name of the agent that detected the risk.
    """
    _logger.warning(
        "【_handle_high_risk_alert】高风险警报: session_id=%s, agent=%s",
        session_id,
        current_agent,
    )

    if "conversation_history" not in result:
        result["conversation_history"] = []
    result["conversation_history"].append({
        "agent": current_agent,
        "action": "high_risk_alert",
        "content": HIGH_RISK_ALERT_MESSAGE,
        "timestamp": datetime.utcnow().isoformat(),
    })

    orchestrator.update_session_context(session_id, result)
    await set_redis_cache(f"session:{session_id}", dict(result), expire=SESSION_TTL)


async def _generate_welcome_message(user_type: str = "suspect") -> str:
    """生成欢迎语和隐私条款告知

    Args:
        user_type: 用户类型

    Returns:
        欢迎语文本
    """
    welcome = f"""您好，欢迎使用刑事辩护初期咨询系统。

我是您的智能法律咨询助手，可以帮助您了解相关法律问题和权利义务。

在开始之前，请您仔细阅读以下重要提示：

【权利义务告知】

1. 本系统提供的仅为初步法律咨询参考，不构成正式法律意见
2. 律师-当事人关系将在您与律师正式签订委托合同后建立
3. 为保护您的权益，在咨询过程中请您如实陈述案件情况
4. 您有权随时终止咨询并寻求当面法律服务
5. 我们会严格保护您的个人信息和案件隐私

请回复"同意"或"确认"表示您已阅读并理解上述告知内容。"""

    return disclaimer.inject(welcome)


async def _create_consultation_record(
    session_id: str, user_id: str, user_type: str, db: AsyncSession
) -> str:
    """创建咨询数据库记录

    Args:
        session_id: 会话ID
        user_id: 用户ID
        user_type: 用户类型
        db: 数据库会话

    Returns:
        咨询记录ID
    """
    consultation = Consultation(
        client_id=user_id,
        user_type=user_type,
        consent_given=False,
        status=ConsultationStatus.PENDING,
    )
    db.add(consultation)
    await db.commit()
    await db.refresh(consultation)
    _logger.info("【_create_consultation_record】咨询记录创建: consultation_id=%s", consultation.id)
    return consultation.id


async def _save_message_to_db(
    consultation_id: str,
    session_id: str,
    content: str,
    sender_type: str,
    sender_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """保存消息到数据库

    Args:
        consultation_id: 咨询记录ID
        session_id: 会话ID
        content: 消息内容
        sender_type: 发送者类型
        sender_id: 发送者ID
        agent_name: Agent名称
        db: 数据库会话

    Returns:
        消息ID
    """
    if not db:
        return str(uuid.uuid4())

    message = ConsultationMessage(
        consultation_id=consultation_id,
        sender_type=sender_type,
        sender_id=sender_id,
        content=content,
        agent_name=agent_name,
        message_type="text",
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message.id


async def _verify_session_ownership(
    session_id: str, user_id: str, allow_lawyer: bool = False
) -> Optional[ConsultationState]:
    """验证会话所有权并获取会话状态

    Args:
        session_id: 会话ID
        user_id: 用户ID
        allow_lawyer: 是否允许律师访问

    Returns:
        会话状态，如果验证失败返回None
    """
    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        return None

    cached_user_id = state.get("user_id", "")
    user_role = getattr(state, "user_role", None)

    if cached_user_id == user_id:
        return state

    if allow_lawyer and cached_user_id != user_id:
        return None

    return None


@router.post("", response_model=CreateSessionResponse)
async def create_session(
    request: CreateSessionRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新会话

    创建新的咨询会话，初始化状态，返回欢迎语。

    Args:
        request: 创建会话请求参数
        current_user: 当前认证用户
        db: 数据库会话

    Returns:
        会话创建响应，包含session_id和欢迎语
    """
    _logger.info(
        "【create_session】创建会话请求: user_id=%s, user_type=%s",
        current_user["user_id"],
        request.user_type,
    )

    session_id = str(uuid.uuid4())
    user_id = current_user["user_id"]
    user_type = request.user_type if request.user_type else "suspect"

    consultation_id = await _create_consultation_record(session_id, user_id, user_type, db)

    welcome_message = await _generate_welcome_message(user_type)

    state: ConsultationState = {
        "consultation_id": consultation_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_type": user_type,
        "consent_given": False,
        "facts_raw": [],
        "facts_structured": {},
        "applied_laws": [],
        "current_agent": "Receptionist",
        "pending_questions": [],
        "alert_triggered": False,
        "conversation_history": [],
        "user_role": current_user.get("role", "client"),
    }

    orchestrator.update_session_context(session_id, state)

    await set_redis_cache(
        f"session:{session_id}",
        dict(state),
        expire=SESSION_TTL,
    )

    _logger.info("【create_session】会话创建成功: session_id=%s, consultation_id=%s", session_id, consultation_id)

    return CreateSessionResponse(
        session_id=session_id,
        welcome_message=welcome_message,
        current_agent="Receptionist",
        created_at=datetime.utcnow(),
    )


@router.post("/{session_id}/message", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发送消息

    处理用户消息，调用对应的Agent节点，返回Agent回复。

    Args:
        session_id: 会话ID
        request: 发送消息请求参数
        current_user: 当前认证用户
        db: 数据库会话

    Returns:
        Agent回复响应
    """
    _logger.info(
        "【send_message】发送消息: session_id=%s, user_id=%s, content=%s",
        session_id,
        current_user["user_id"],
        request.content[:50],
    )

    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        _logger.warning("【send_message】会话不存在: session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    if state.get("user_id") != current_user["user_id"]:
        _logger.warning(
            "【send_message】无权访问会话: session_id=%s, user_id=%s",
            session_id,
            current_user["user_id"],
        )
        raise HTTPException(status_code=403, detail="无权访问此会话")

    if not state.get("consent_given"):
        _logger.warning("【send_message】用户未同意隐私条款: session_id=%s", session_id)
        raise HTTPException(status_code=403, detail="请先确认隐私条款")

    if "facts_raw" not in state:
        state["facts_raw"] = []
    state["facts_raw"].append(request.content)

    current_agent = state.get("current_agent", "Receptionist")

    # 循环保护检查
    loop_count = state.get("fact_law_loop_count", 0)
    max_loops = 10
    if loop_count > 0:
        _logger.info(
            "【send_message】当前循环次数: %d/%d, coverage_rate: %.2f",
            loop_count,
            max_loops,
            state.get("facts_coverage_rate", 0.0),
        )
        if loop_count >= max_loops:
            _logger.warning(
                "【send_message】已达到最大循环次数 %d，将强制进入风险评估",
                max_loops,
            )

    try:
        result = await orchestrator.run_node(current_agent, state)

        response_content = result.get("final_output", "")
        next_agent = result.get("current_agent", current_agent)

        if result.get("alert_triggered"):
            await _handle_high_risk_alert(session_id, result, current_agent)
            raise HTTPException(
                status_code=403,
                detail=HIGH_RISK_ALERT_MESSAGE,
            )

        if "conversation_history" not in result:
            result["conversation_history"] = []
        result["conversation_history"].append({
            "agent": current_agent,
            "user_message": request.content,
            "agent_response": response_content,
            "timestamp": datetime.utcnow().isoformat(),
        })

        orchestrator.update_session_context(session_id, result)
        await set_redis_cache(f"session:{session_id}", dict(result), expire=SESSION_TTL)

        await _save_message_to_db(
            consultation_id=result.get("consultation_id", ""),
            session_id=session_id,
            content=request.content,
            sender_type="user",
            sender_id=current_user["user_id"],
            db=db,
        )

        if response_content:
            await _save_message_to_db(
                consultation_id=result.get("consultation_id", ""),
                session_id=session_id,
                content=response_content,
                sender_type="agent",
                agent_name=current_agent,
                db=db,
            )

        message_id = str(uuid.uuid4())

        _logger.info(
            "【send_message】消息处理完成: session_id=%s, agent=%s, next_agent=%s",
            session_id,
            current_agent,
            next_agent,
        )

        return SendMessageResponse(
            session_id=session_id,
            message_id=message_id,
            agent_name=current_agent,
            response_content=response_content,
            is_complete=False,
            pending_questions=result.get("pending_questions"),
            alert_triggered=result.get("alert_triggered", False),
            created_at=datetime.utcnow(),
        )

    except Exception as e:
        _logger.error("【send_message】消息处理异常: session_id=%s, error=%s", session_id, str(e))
        raise HTTPException(status_code=500, detail="消息处理失败，请稍后重试")


@router.post("/{session_id}/confirm-consent", response_model=ConfirmConsentResponse)
async def confirm_consent(
    session_id: str,
    request: ConfirmConsentRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """确认隐私同意

    更新consent_given状态，触发下一Agent执行。

    Args:
        session_id: 会话ID
        request: 确认同意请求参数
        current_user: 当前认证用户
        db: 数据库会话

    Returns:
        确认结果响应
    """
    _logger.info(
        "【confirm_consent】确认隐私同意: session_id=%s, consent_accepted=%s, user_id=%s",
        session_id,
        request.consent_accepted,
        current_user["user_id"],
    )

    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        _logger.warning("【confirm_consent】会话不存在: session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    if state.get("user_id") != current_user["user_id"]:
        _logger.warning(
            "【confirm_consent】无权访问会话: session_id=%s, user_id=%s",
            session_id,
            current_user["user_id"],
        )
        raise HTTPException(status_code=403, detail="无权访问此会话")

    consultation_id = state.get("consultation_id")

    if consultation_id:
        consultation_result = await db.execute(
            select(Consultation).where(Consultation.id == consultation_id)
        )
        consultation = consultation_result.scalar_one_or_none()
        if consultation:
            consultation.consent_given = request.consent_accepted
            await db.commit()

    if request.consent_accepted:
        state["consent_given"] = True

        if request.identity_info:
            state["identity_info"] = request.identity_info

        next_prompt = "感谢您的同意。请告诉我您的身份类型（嫌疑人、受害者或家属）和案件发生的大概城市。"
        conversation_started = False

        state["conversation_history"].append({
            "agent": "Receptionist",
            "action": "consent_confirmed",
            "timestamp": datetime.utcnow().isoformat(),
        })

    else:
        state["consent_given"] = False
        next_prompt = "如需继续使用咨询服务，请回复'同意'确认您已阅读并理解权利义务告知。"
        conversation_started = False

    orchestrator.update_session_context(session_id, state)
    await set_redis_cache(f"session:{session_id}", dict(state), expire=SESSION_TTL)

    _logger.info(
        "【confirm_consent】隐私同意确认完成: session_id=%s, consent_given=%s",
        session_id,
        request.consent_accepted,
    )

    return ConfirmConsentResponse(
        session_id=session_id,
        success=True,
        current_agent=state.get("current_agent", "Receptionist"),
        next_prompt=next_prompt,
        conversation_started=conversation_started,
    )


@router.get("/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取会话状态

    返回当前会话状态，供律师端恢复。

    Args:
        session_id: 会话ID
        current_user: 当前认证用户

    Returns:
        会话状态响应
    """
    _logger.info(
        "【get_session_state】获取会话状态: session_id=%s, user_id=%s, role=%s",
        session_id,
        current_user["user_id"],
        current_user["role"],
    )

    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        _logger.warning("【get_session_state】会话不存在: session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    user_id = state.get("user_id", "")
    is_owner = user_id == current_user["user_id"]
    is_lawyer_or_admin = current_user["role"] in ["lawyer", "admin"]

    if not is_owner and not is_lawyer_or_admin:
        _logger.warning(
            "【get_session_state】无权访问会话: session_id=%s, user_id=%s",
            session_id,
            current_user["user_id"],
        )
        raise HTTPException(status_code=403, detail="无权访问此会话")

    _logger.info(
        "【get_session_state】会话状态获取成功: session_id=%s, current_agent=%s",
        session_id,
        state.get("current_agent"),
    )

    return SessionStateResponse(
        session_id=session_id,
        consultation_id=state.get("consultation_id"),
        user_id=user_id,
        user_type=state.get("user_type", "suspect"),
        consent_given=state.get("consent_given", False),
        current_agent=state.get("current_agent", "Receptionist"),
        conversation_history=state.get("conversation_history", []),
        facts_raw=state.get("facts_raw", []),
        facts_structured=state.get("facts_structured"),
        applied_laws=state.get("applied_laws", []),
        pending_questions=state.get("pending_questions", []),
        alert_triggered=state.get("alert_triggered", False),
        risk_assessment=state.get("risk_assessment"),
        final_output=state.get("final_output"),
        lawyer_id=state.get("lawyer_id"),
        status="active",
    )


@router.put("/{session_id}/review", response_model=LawyerReviewResponse)
async def lawyer_review(
    session_id: str,
    request: LawyerReviewRequest,
    current_user: dict = Depends(get_current_user),
):
    """律师审核反馈

    处理律师对报告的审核决定：
    - approved: 批准报告，流程结束
    - revise_facts: 要求修改事实，返回FactDigger重新收集
    - revise_risk: 要求修改风险评估，返回RiskAssessor重新评估

    Args:
        session_id: 会话ID
        request: 律师审核请求参数
        current_user: 当前认证用户

    Returns:
        律师审核响应
    """
    _logger.info(
        "【lawyer_review】律师审核请求: session_id=%s, decision=%s, user_id=%s, role=%s",
        session_id,
        request.decision,
        current_user["user_id"],
        current_user["role"],
    )

    if current_user["role"] not in ["lawyer", "admin"]:
        _logger.warning(
            "【lawyer_review】权限不足: 只有律师或管理员可以审核 session_id=%s, role=%s",
            session_id,
            current_user["role"],
        )
        raise HTTPException(status_code=403, detail="只有律师或管理员可以审核")

    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        _logger.warning("【lawyer_review】会话不存在: session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    if not state.get("awaiting_lawyer_review"):
        _logger.warning(
            "【lawyer_review】会话未等待审核: session_id=%s, awaiting=%s",
            session_id,
            state.get("awaiting_lawyer_review"),
        )
        raise HTTPException(status_code=400, detail="此会话未在等待律师审核")

    if request.decision not in ["approved", "revise_facts", "revise_risk"]:
        _logger.warning("【lawyer_review】无效的审核决定: decision=%s", request.decision)
        raise HTTPException(status_code=400, detail="无效的审核决定")

    if request.decision == "approved" and request.final_output:
        state["final_output"] = request.final_output

    if request.feedback:
        state["lawyer_feedback"] = request.feedback

    try:
        result = await orchestrator.process_lawyer_feedback(
            session_id=session_id,
            decision=request.decision,
            feedback=request.feedback,
        )

        next_agent_map = {
            "approved": None,
            "revise_facts": "fact_digger",
            "revise_risk": "risk_assessor",
        }
        next_agent = next_agent_map.get(request.decision)

        if request.decision != "approved" and next_agent:
            result = await orchestrator.run_node(next_agent, result)
            orchestrator.update_session_context(session_id, result)
            await set_redis_cache(f"session:{session_id}", dict(result), expire=SESSION_TTL)

        if request.decision == "approved":
            state["current_agent"] = "END"
            state["status"] = "completed"
            orchestrator.update_session_context(session_id, state)
            await set_redis_cache(f"session:{session_id}", dict(state), expire=SESSION_TTL)

        _logger.info(
            "【lawyer_review】律师审核处理完成: session_id=%s, decision=%s, next_agent=%s",
            session_id,
            request.decision,
            next_agent,
        )

        return LawyerReviewResponse(
            session_id=session_id,
            decision=request.decision,
            feedback=request.feedback,
            next_agent=next_agent,
            processed_at=datetime.utcnow(),
        )

    except Exception as e:
        _logger.error("【lawyer_review】律师审核处理异常: session_id=%s, error=%s", session_id, str(e))
        raise HTTPException(status_code=500, detail="审核处理失败，请稍后重试")


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: dict = Depends(get_current_user),
):
    """获取会话列表

    根据用户角色返回不同的会话列表：
    - admin: 所有会话
    - lawyer: 分配给自己的会话
    - client: 自己的会话

    Args:
        current_user: 当前认证用户

    Returns:
        会话列表响应
    """
    _logger.info(
        "【list_sessions】会话列表请求: user_id=%s, role=%s",
        current_user["user_id"],
        current_user["role"],
    )

    active_sessions = orchestrator.get_active_sessions()
    sessions = []

    for sess_id, state in active_sessions.items():
        user_id = state.get("user_id", "")

        if current_user["role"] == "client" and user_id != current_user["user_id"]:
            continue

        if current_user["role"] == "lawyer":
            lawyer_id = state.get("lawyer_id")
            if lawyer_id and lawyer_id != current_user["user_id"]:
                continue

        sessions.append(SessionListItem(
            session_id=sess_id,
            consultation_id=state.get("consultation_id", ""),
            user_id=user_id,
            user_type=state.get("user_type", "suspect"),
            current_agent=state.get("current_agent", "Receptionist"),
            status="active" if state.get("awaiting_lawyer_review") else "in_progress",
            consent_given=state.get("consent_given", False),
            alert_triggered=state.get("alert_triggered", False),
            awaiting_lawyer_review=state.get("awaiting_lawyer_review", False),
            risk_level=state.get("risk_assessment", {}).get("risk_level") if state.get("risk_assessment") else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))

    _logger.info("【list_sessions】会话列表返回: total=%d", len(sessions))

    return SessionListResponse(
        sessions=sessions,
        total=len(sessions),
    )


@router.post("/{session_id}/close", response_model=SessionCloseResponse)
async def close_session(
    session_id: str,
    request: SessionCloseRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """关闭会话

    关闭指定会话，清理会话状态。

    Args:
        session_id: 会话ID
        request: 关闭会话请求参数
        current_user: 当前认证用户

    Returns:
        关闭会话响应
    """
    _logger.info(
        "【close_session】关闭会话请求: session_id=%s, user_id=%s, role=%s",
        session_id,
        current_user["user_id"],
        current_user["role"],
    )

    state = orchestrator.get_session_context(session_id)

    if not state:
        state = await get_redis_cache_json(f"session:{session_id}")
        if state:
            state = ConsultationState(**state) if isinstance(state, dict) else state

    if not state:
        _logger.warning("【close_session】会话不存在: session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    user_id = state.get("user_id", "")
    is_owner = user_id == current_user["user_id"]
    is_lawyer_or_admin = current_user["role"] in ["lawyer", "admin"]

    if not is_owner and not is_lawyer_or_admin:
        _logger.warning(
            "【close_session】无权关闭会话: session_id=%s, user_id=%s",
            session_id,
            current_user["user_id"],
        )
        raise HTTPException(status_code=403, detail="无权关闭此会话")

    reason = request.reason if request else None

    if "conversation_history" not in state:
        state["conversation_history"] = []
    state["conversation_history"].append({
        "agent": "system",
        "action": "session_closed",
        "reason": reason,
        "closed_by": current_user["user_id"],
        "timestamp": datetime.utcnow().isoformat(),
    })

    state["current_agent"] = "END"
    orchestrator.update_session_context(session_id, state)
    await set_redis_cache(f"session:{session_id}", dict(state), expire=SESSION_TTL)

    _logger.info(
        "【close_session】会话关闭成功: session_id=%s, reason=%s",
        session_id,
        reason,
    )

    return SessionCloseResponse(
        session_id=session_id,
        success=True,
        message=f"会话已成功关闭{'，原因：' + reason if reason else ''}",
        closed_at=datetime.utcnow(),
    )


@router.websocket("/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 通信端点

    建立 WebSocket 连接，支持双向实时消息通信和心跳机制。

    Args:
        websocket: WebSocket 连接对象
        session_id: 会话ID
    """
    await manager.connect(websocket, session_id)

    heartbeat_task = None
    state = None

    try:
        state = orchestrator.get_session_context(session_id)

        if not state:
            state = await get_redis_cache_json(f"session:{session_id}")
            if state:
                state = ConsultationState(**state) if isinstance(state, dict) else state

        if not state:
            await websocket.send_json({
                "type": "error",
                "content": "会话不存在或已过期",
            })
            await websocket.close()
            return

        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket, session_id))

        await websocket.send_json({
            "type": "ack",
            "content": "连接已建立",
            "session_id": session_id,
            "current_agent": state.get("current_agent", "Receptionist"),
        })

        while True:
            data = await websocket.receive_text()

            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "无效的JSON格式",
                })
                continue

            message_type = message_data.get("type", "message")

            if message_type == "heartbeat":
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "timestamp": datetime.utcnow().isoformat(),
                })
                continue

            if message_type == "message":
                content = message_data.get("content", "")

                if not state.get("consent_given") and "同意" not in content and "确认" not in content:
                    await websocket.send_json({
                        "type": "message",
                        "agent_name": "Receptionist",
                        "content": "请先回复'同意'确认您已阅读并理解权利义务告知。",
                        "session_id": session_id,
                    })
                    continue

                if "facts_raw" not in state:
                    state["facts_raw"] = []
                state["facts_raw"].append(content)

                current_agent = state.get("current_agent", "Receptionist")

                # 循环保护检查
                loop_count = state.get("fact_law_loop_count", 0)
                max_loops = 10
                if loop_count > 0:
                    _logger.info(
                        "【websocket_endpoint】当前循环次数: %d/%d, coverage_rate: %.2f",
                        loop_count,
                        max_loops,
                        state.get("facts_coverage_rate", 0.0),
                    )
                    if loop_count >= max_loops:
                        _logger.warning(
                            "【websocket_endpoint】已达到最大循环次数 %d，将强制进入风险评估",
                            max_loops,
                        )

                try:
                    result = await orchestrator.run_node(current_agent, state)

                    response_content = result.get("final_output", "")
                    next_agent = result.get("current_agent", current_agent)

                    if result.get("alert_triggered"):
                        await _handle_high_risk_alert(session_id, result, current_agent)
                        await websocket.send_json({
                            "type": "alert",
                            "content": HIGH_RISK_ALERT_MESSAGE,
                            "agent_name": current_agent,
                            "session_id": session_id,
                        })
                    else:
                        await websocket.send_json({
                            "type": "message",
                            "agent_name": current_agent,
                            "content": response_content,
                            "session_id": session_id,
                        })

                        if "conversation_history" not in result:
                            result["conversation_history"] = []
                        result["conversation_history"].append({
                            "agent": current_agent,
                            "user_message": content,
                            "agent_response": response_content,
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                        state = result
                        orchestrator.update_session_context(session_id, result)
                        await set_redis_cache(f"session:{session_id}", dict(result), expire=SESSION_TTL)

                        await websocket.send_json({
                            "type": "ack",
                            "content": "消息已处理",
                            "agent_name": current_agent,
                        })

                except Exception as e:
                    _logger.error("【websocket_endpoint】消息处理异常: %s", str(e))
                    await websocket.send_json({
                        "type": "error",
                        "content": "消息处理失败，请稍后重试",
                    })

    except WebSocketDisconnect:
        _logger.info("【websocket_endpoint】客户端断开连接: session_id=%s", session_id)
    except Exception as e:
        _logger.error("【websocket_endpoint】WebSocket异常: session_id=%s, error=%s", session_id, str(e))
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()

        manager.disconnect(websocket, session_id)


async def _heartbeat_loop(websocket: WebSocket, session_id: str) -> None:
    """WebSocket 心跳循环

    定期发送心跳包以保持连接活跃。

    Args:
        websocket: WebSocket 连接对象
        session_id: 会话ID
    """
    while True:
        try:
            await asyncio.sleep(30)
            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat(),
            })
        except Exception:
            break