from typing import List, Optional, TypedDict


class ConsultationState(TypedDict, total=False):
    """Global state object shared across all agents in the LangGraph pipeline"""

    consultation_id: str  # 咨询会话的唯一标识符，用于追踪和关联整个咨询过程
    user_id: str  # 用户ID，标识进行咨询的用户身份
    session_id: str  # 会话ID，用于标识当前咨询会话
    user_type: str  # 用户类型：suspect（嫌疑人）/ victim（受害者）/ family（家属）
    consent_given: bool  # 是否已获得用户的知情同意
    facts_raw: List[str]  # 原始用户叙述段落，包含未经处理的案件描述
    facts_structured: dict  # 通过LLM函数调用提取的结构化案件事实
    applied_laws: List[dict]  # 法律法规检索结果，包含罪名、条款、相关案例
    current_agent: str  # 当前活跃的agent名称
    pending_questions: List[str]  # 待提问的后续问题列表
    alert_triggered: bool  # 是否触发高风险陈述警报
    risk_assessment: Optional[dict]  # 可选的风险评估结果
    lawyer_review_needed: bool  # 是否需要律师审核
    final_output: str  # 最终输出内容，包括完整的咨询报告和建议
    conversation_history: List[dict]  # 对话历史记录，用于维护多轮对话的上下文
    report_draft: Optional[str]  # 可选的报告草稿，在咨询过程中生成的中期报告
    service_plan: Optional[dict]  # 可选的服务计划，包含后续法律服务建议
    lawyer_id: Optional[str]  # 可选的律师ID，分配给此案件的律师标识
