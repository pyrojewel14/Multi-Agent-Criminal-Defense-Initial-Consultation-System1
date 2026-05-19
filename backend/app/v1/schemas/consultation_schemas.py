from datetime import datetime
from typing import Optional, List, Literal, Any
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


class LawyerSessionItem(BaseModel):
    """律师端会话列表项"""
    id: str = Field(..., description="会话ID")
    client_id: str = Field(..., description="客户ID")
    client_username: Optional[str] = Field(None, description="客户用户名")
    client_real_name: Optional[str] = Field(None, description="客户真实姓名")
    user_type: str = Field(..., description="用户类型: suspect, victim, family")
    status: str = Field(..., description="会话状态")
    risk_level: Optional[str] = Field(None, description="风险等级: low, medium, high, critical")
    alert_triggered: bool = Field(False, description="是否触发高风险告警")
    lawyer_review_needed: bool = Field(False, description="是否需要律师审核")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    class Config:
        from_attributes = True


class MessageHistoryItem(BaseModel):
    """消息历史项"""
    id: str
    sender_type: str = Field(..., description="发送者类型: user, agent, lawyer")
    sender_id: Optional[str] = None
    content: str
    agent_name: Optional[str] = None
    message_type: str = "text"
    created_at: datetime

    class Config:
        from_attributes = True


class LawyerSessionDetail(BaseModel):
    """律师端会话详情"""
    id: str
    client_id: str
    client_username: Optional[str] = None
    client_real_name: Optional[str] = None
    user_type: str
    consent_given: bool
    status: str
    risk_level: Optional[str] = None
    alert_triggered: bool
    lawyer_review_needed: bool
    facts_raw: Optional[List[str]] = Field(None, description="原始叙述段落")
    facts_structured: Optional[dict] = Field(None, description="结构化案件事实")
    applied_laws: Optional[List[dict]] = Field(None, description="适用的法律法规")
    risk_assessment: Optional[dict] = Field(None, description="风险评估结果")
    report_draft: Optional[str] = Field(None, description="报告草稿")
    service_plan: Optional[dict] = Field(None, description="服务计划")
    final_output: Optional[str] = Field(None, description="最终输出")
    conversation_history: Optional[List[MessageHistoryItem]] = Field(None, description="对话历史")
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApproveReportRequest(BaseModel):
    """审核报告请求"""
    final_output: str = Field(..., description="律师确认的最终报告内容")
    feedback: Optional[str] = Field(None, description="律师反馈意见")

    class Config:
        from_attributes = True


class ApproveReportResponse(BaseModel):
    """审核报告响应"""
    success: bool = Field(True, description="操作是否成功")
    message: str = Field(..., description="操作结果消息")
    session_id: str = Field(..., description="会话ID")
    approved_at: datetime = Field(..., description="批准时间")

    class Config:
        from_attributes = True


class RejectSessionRequest(BaseModel):
    """退回会话请求"""
    target_node: str = Field(..., description="退回目标节点: fact_digger, risk_assessor")
    reason: Optional[str] = Field(None, description="退回原因")
    feedback: Optional[str] = Field(None, description="具体修改要求")

    class Config:
        from_attributes = True


class RejectSessionResponse(BaseModel):
    """退回会话响应"""
    success: bool = Field(True, description="操作是否成功")
    message: str = Field(..., description="操作结果消息")
    session_id: str = Field(..., description="会话ID")
    target_node: str = Field(..., description="退回目标节点")
    rejected_at: datetime = Field(..., description="退回时间")

    class Config:
        from_attributes = True


class InterventionResponse(BaseModel):
    """人工接管会话响应"""
    success: bool = Field(True, description="操作是否成功")
    message: str = Field(..., description="操作结果消息")
    session_id: str = Field(..., description="会话ID")
    intervened_at: datetime = Field(..., description="接管时间")
    current_agent: str = Field("Lawyer", description="当前活跃的agent")

    class Config:
        from_attributes = True


class RiskAlertItem(BaseModel):
    """高风险告警项"""
    id: str
    session_id: str = Field(..., description="关联的会话ID")
    client_id: str = Field(..., description="客户ID")
    client_real_name: Optional[str] = Field(None, description="客户真实姓名")
    risk_type: str = Field(..., description="风险类型")
    risk_level: str = Field(..., description="风险等级: low, medium, high, critical")
    details: Optional[str] = Field(None, description="风险详情")
    is_read: bool = Field(False, description="是否已读")
    created_at: datetime = Field(..., description="告警时间")

    class Config:
        from_attributes = True


class LawyerSessionListResponse(BaseModel):
    """律师端会话列表响应"""
    sessions: List[LawyerSessionItem]
    total: int
    page: int
    page_size: int


class CreateSessionRequest(BaseModel):
    """会话创建请求模型"""
    client_id: str = Field(..., description="客户端ID")
    user_type: Literal["suspect", "victim", "family"] = Field(..., description="用户类型")
    initial_message: Optional[str] = Field(None, description="初始消息内容")
    source: Optional[str] = Field(None, description="来源渠道")


class CreateSessionResponse(BaseModel):
    """会话创建响应模型"""
    session_id: str = Field(..., description="会话ID")
    status: str = Field(..., description="会话状态")
    created_at: datetime = Field(..., description="创建时间")
    ws_token: Optional[str] = Field(None, description="WebSocket认证令牌")
    consent_required: bool = Field(..., description="是否需要确认隐私同意")


class SendMessageRequest(BaseModel):
    """发送消息请求模型"""
    session_id: str = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, description="消息内容")
    message_type: Literal["text", "action", "system"] = Field(default="text", description="消息类型")
    metadata: Optional[dict[str, Any]] = Field(None, description="附加元数据")


class SendMessageResponse(BaseModel):
    """发送消息响应模型"""
    message_id: str = Field(..., description="消息ID")
    session_id: str = Field(..., description="会话ID")
    status: str = Field(..., description="发送状态")
    timestamp: datetime = Field(..., description="发送时间戳")


class ConfirmConsentRequest(BaseModel):
    """隐私同意确认请求模型"""
    session_id: str = Field(..., description="会话ID")
    consent_given: bool = Field(..., description="是否同意隐私协议")
    consent_timestamp: datetime = Field(..., description="同意时间戳")
    consent_version: str = Field(..., description="隐私协议版本")
    ip_address: Optional[str] = Field(None, description="IP地址")
    user_agent: Optional[str] = Field(None, description="用户代理信息")


class ConfirmConsentResponse(BaseModel):
    """隐私同意确认响应模型"""
    session_id: str = Field(..., description="会话ID")
    consent_confirmed: bool = Field(..., description="同意是否已确认")
    confirmed_at: datetime = Field(..., description="确认时间")
    next_step: str = Field(..., description="下一步操作提示")


class SessionStateResponse(BaseModel):
    """会话状态响应模型"""
    session_id: str = Field(..., description="会话ID")
    status: Literal["waiting_consent", "in_progress", "pending_review", "completed", "cancelled"] = Field(..., description="会话状态")
    current_agent: Optional[str] = Field(None, description="当前活跃的Agent名称")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="会话进度 0.0-1.0")
    message_count: int = Field(default=0, ge=0, description="消息总数")
    last_activity: Optional[datetime] = Field(None, description="最后活动时间")
    risk_level: Optional[Literal["low", "medium", "high"]] = Field(None, description="风险等级")
    lawyer_assigned: bool = Field(default=False, description="是否已分配律师")
    consent_given: bool = Field(default=False, description="是否已同意隐私协议")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class LawyerSessionItem(BaseModel):
    """律师端会话列表项模型"""
    session_id: str = Field(..., description="会话ID")
    client_id: str = Field(..., description="客户端ID")
    client_username: Optional[str] = Field(None, description="客户端用户名")
    client_real_name: Optional[str] = Field(None, description="客户端真实姓名")
    user_type: Literal["suspect", "victim", "family"] = Field(..., description="用户类型")
    status: Literal["pending_review", "completed", "cancelled"] = Field(..., description="会话状态")
    risk_level: Optional[Literal["low", "medium", "high"]] = Field(None, description="风险等级")
    created_at: datetime = Field(..., description="创建时间")
    summary: Optional[str] = Field(None, description="会话摘要")
    agent_count: int = Field(default=0, description="参与的Agent数量")


class LawyerSessionDetail(BaseModel):
    """律师端会话详情模型"""
    session_id: str = Field(..., description="会话ID")
    client_id: str = Field(..., description="客户端ID")
    client_username: Optional[str] = Field(None, description="客户端用户名")
    client_real_name: Optional[str] = Field(None, description="客户端真实姓名")
    user_type: Literal["suspect", "victim", "family"] = Field(..., description="用户类型")
    status: str = Field(..., description="会话状态")
    facts_structured: Optional[str] = Field(None, description="结构化事实陈述")
    applied_laws: Optional[str] = Field(None, description="适用法律条款")
    final_output: Optional[str] = Field(None, description="最终输出报告")
    risk_level: Optional[Literal["low", "medium", "high"]] = Field(None, description="风险等级")
    risk_alerts: List["RiskAlertItem"] = Field(default_factory=list, description="风险警报列表")
    consent_given: bool = Field(..., description="是否已同意隐私协议")
    consent_timestamp: Optional[datetime] = Field(None, description="同意时间戳")
    lawyer_assigned: bool = Field(default=False, description="是否已分配律师")
    lawyer_id: Optional[str] = Field(None, description="分配的律师ID")
    lawyer_name: Optional[str] = Field(None, description="分配的律师姓名")
    report_generated: bool = Field(default=False, description="报告是否已生成")
    report_approved: bool = Field(default=False, description="报告是否已审核")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class ApproveReportRequest(BaseModel):
    """审核报告请求模型"""
    session_id: str = Field(..., description="会话ID")
    approved: bool = Field(..., description="是否批准报告")
    comments: Optional[str] = Field(None, description="审核意见")
    modified_sections: Optional[dict[str, str]] = Field(None, description="修改的章节内容")


class ApproveReportResponse(BaseModel):
    """审核报告响应模型"""
    session_id: str = Field(..., description="会话ID")
    approved: bool = Field(..., description="是否已批准")
    approved_by: str = Field(..., description="审核人ID")
    approved_at: datetime = Field(..., description="审核时间")
    comments: Optional[str] = Field(None, description="审核意见")
    next_step: str = Field(..., description="下一步操作")


class RejectSessionRequest(BaseModel):
    """拒绝会话请求模型"""
    session_id: str = Field(..., description="会话ID")
    reason: str = Field(..., min_length=10, description="拒绝原因")
    rejection_type: Literal["invalid_case", "outside_jurisdiction", "requires_specialist", "client_request"] = Field(..., description="拒绝类型")


class RejectSessionResponse(BaseModel):
    """拒绝会话响应模型"""
    session_id: str = Field(..., description="会话ID")
    rejected: bool = Field(..., description="是否已拒绝")
    rejected_by: str = Field(..., description="拒绝人ID")
    rejected_at: datetime = Field(..., description="拒绝时间")
    reason: str = Field(..., description="拒绝原因")
    alternative_action: Optional[str] = Field(None, description="替代建议")


class InterventionResponse(BaseModel):
    """干预响应模型"""
    session_id: str = Field(..., description="会话ID")
    intervention_type: Literal["pause", "redirect", "escalate", "terminate"] = Field(..., description="干预类型")
    reason: str = Field(..., description="干预原因")
    message_to_client: Optional[str] = Field(None, description="发送给客户端的消息")
    notify_lawyers: bool = Field(default=False, description="是否通知律师")
    executed_at: datetime = Field(..., description="执行时间")
    result: Optional[str] = Field(None, description="执行结果")


class RiskAlertItem(BaseModel):
    """风险警报项模型"""
    alert_id: str = Field(..., description="警报ID")
    alert_type: Literal["self_incrimination", "misinformation", "urgency", "complexity", "safety"] = Field(..., description="警报类型")
    severity: Literal["low", "medium", "high", "critical"] = Field(..., description="严重程度")
    title: str = Field(..., description="警报标题")
    description: str = Field(..., description="警报描述")
    detected_at: datetime = Field(..., description="检测时间")
    acknowledged: bool = Field(default=False, description="是否已确认")
    acknowledged_by: Optional[str] = Field(None, description="确认人ID")
    acknowledged_at: Optional[datetime] = Field(None, description="确认时间")
    metadata: Optional[dict[str, Any]] = Field(None, description="附加元数据")


class WSMessage(BaseModel):
    """WebSocket消息基类模型"""
    type: str = Field(..., description="消息类型")
    session_id: str = Field(..., description="会话ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
    message_id: Optional[str] = Field(None, description="消息ID")
    correlation_id: Optional[str] = Field(None, description="关联ID用于追踪")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class WSAgentMessage(BaseModel):
    """WebSocket Agent消息模型"""
    type: Literal["agent_message"] = Field(default="agent_message", description="消息类型")
    session_id: str = Field(..., description="会话ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
    message_id: Optional[str] = Field(None, description="消息ID")
    correlation_id: Optional[str] = Field(None, description="关联ID")
    agent_name: str = Field(..., description="Agent名称")
    content: str = Field(..., description="消息内容")
    format: Literal["text", "markdown", "structured"] = Field(default="text", description="内容格式")
    actions_available: Optional[List[str]] = Field(None, description="可用操作列表")


class WSActionRequired(BaseModel):
    """WebSocket需要操作消息模型"""
    type: Literal["action_required"] = Field(default="action_required", description="消息类型")
    session_id: str = Field(..., description="会话ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
    message_id: Optional[str] = Field(None, description="消息ID")
    correlation_id: Optional[str] = Field(None, description="关联ID")
    action_type: str = Field(..., description="操作类型")
    title: str = Field(..., description="操作标题")
    description: str = Field(..., description="操作描述")
    options: List[dict[str, str]] = Field(default_factory=list, description="操作选项列表")
    required: bool = Field(default=True, description="是否必需")
    timeout: Optional[int] = Field(None, description="超时时间（秒）")


class WSNotice(BaseModel):
    """WebSocket通知消息模型"""
    type: Literal["notice"] = Field(default="notice", description="消息类型")
    session_id: str = Field(..., description="会话ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
    message_id: Optional[str] = Field(None, description="消息ID")
    correlation_id: Optional[str] = Field(None, description="关联ID")
    notice_type: Literal["info", "warning", "success", "progress"] = Field(..., description="通知类型")
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    auto_dismiss: bool = Field(default=False, description="是否自动消失")
    dismiss_after: Optional[int] = Field(None, description="自动消失时间（秒）")


class WSError(BaseModel):
    """WebSocket错误消息模型"""
    type: Literal["error"] = Field(default="error", description="消息类型")
    session_id: str = Field(..., description="会话ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
    message_id: Optional[str] = Field(None, description="消息ID")
    correlation_id: Optional[str] = Field(None, description="关联ID")
    error_code: str = Field(..., description="错误代码")
    error_message: str = Field(..., description="错误消息")
    details: Optional[dict[str, Any]] = Field(None, description="错误详情")
    recoverable: bool = Field(default=True, description="是否可恢复")
    retry_available: bool = Field(default=False, description="是否可重试")