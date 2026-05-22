from typing import Any, Dict, Literal, Optional

from langgraph.graph import END, StateGraph

from app.state.consultation_state import ConsultationState
from app.utils.logger import get_logger

from app.agents.receptionist import receptionist_node
from app.agents.fact_digger import fact_digger_node
from app.agents.law_ref import law_ref_node
from app.agents.risk_assessor import risk_assessor_node
from app.agents.service_planner import service_planner_node
from app.agents.human_alert import human_alert_node
from app.errors.exceptions import LLMServiceException, LLMTimeoutException

_logger = get_logger("Orchestrator")

COVERAGE_THRESHOLD = 0.8


def check_consent(state: ConsultationState) -> Literal["continue", "end"]:
    """条件边：根据用户是否同意决定流程走向。

    Args:
        state: 当前咨询状态

    Returns:
        "continue" - 同意，继续到 FactDigger
        "end" - 不同意，结束流程
    """
    if state.get("consent_given"):
        _logger.debug("用户已同意，继续流程")
        return "continue"
    _logger.debug("用户未同意，结束流程")
    return "end"


def check_facts_sufficient(state: ConsultationState) -> Literal["complete", "loop", "alert", "max_loop"]:
    """条件边：根据事实收集覆盖度决定流程走向。

    Args:
        state: 当前咨询状态

    Returns:
        "complete" - 覆盖度 >= 80%，继续到 RiskAssessor
        "loop" - 覆盖度 < 80%，继续追问
        "alert" - 触发人工介入
        "max_loop" - 达到最大循环次数，强制进入 RiskAssessor
    """
    if state.get("alert_triggered"):
        _logger.info("检测到高风险内容，触发人工介入")
        return "alert"

    # 循环计数保护
    loop_count = state.get("fact_law_loop_count", 0)
    max_loops = 10
    if loop_count >= max_loops:
        _logger.warning(
            "【check_facts_sufficient】达到最大循环次数 %d，强制进入风险评估",
            max_loops,
        )
        return "max_loop"

    coverage_rate = state.get("facts_coverage_rate", 0.0)

    if coverage_rate >= COVERAGE_THRESHOLD:
        _logger.info("事实覆盖度 %.2f >= %.2f，流程完成", coverage_rate, COVERAGE_THRESHOLD)
        return "complete"

    _logger.info("事实覆盖度 %.2f < %.2f，需要继续追问", coverage_rate, COVERAGE_THRESHOLD)
    return "loop"


def lawyer_decision(state: ConsultationState) -> Literal["approved", "revise_facts", "revise_risk"]:
    """条件边：根据律师审核决策决定流程走向。

    Args:
        state: 当前咨询状态

    Returns:
        "approved" - 报告已批准，结束流程
        "revise_facts" - 需要修改事实，返回 FactDigger
        "revise_risk" - 需要修改风险评估，返回 RiskAssessor
    """
    decision = state.get("lawyer_decision", "approved")

    if decision == "revise_facts":
        _logger.info("律师决策：需要修改事实，返回 FactDigger")
        return "revise_facts"
    elif decision == "revise_risk":
        _logger.info("律师决策：需要修改风险评估，返回 RiskAssessor")
        return "revise_risk"

    _logger.info("律师决策：报告已批准，流程结束")
    return "approved"


async def human_review_node(state: ConsultationState) -> ConsultationState:
    """HumanReview Agent 节点函数 - 律师审核节点

    等待律师对服务方案和报告草案进行审核，
    根据律师决策更新状态。

    Args:
        state: 当前 ConsultationState

    Returns:
        更新后的 ConsultationState
    """
    _logger.info("【human_review_node】律师审核节点开始执行")

    session_id = state.get("session_id", "unknown")

    report_draft = state.get("report_draft", "")
    service_plan = state.get("service_plan", {})

    if report_draft:
        state["final_output"] = f"""【律师审核请求】

您好，以下是系统生成的初期咨询报告草案，请您审核：

{report_draft}

请选择：
1. 批准此报告
2. 要求修改事实收集
3. 要求修改风险评估
"""
    else:
        state["final_output"] = "报告草案尚未生成，请稍后重试。"

    state["awaiting_lawyer_review"] = True
    state["current_agent"] = "HumanReview"

    if "conversation_history" not in state:
        state["conversation_history"] = []
    state["conversation_history"].append(
        {
            "agent": "HumanReview",
            "action": "awaiting_review",
            "session_id": session_id,
            "has_report": bool(report_draft),
            "has_service_plan": bool(service_plan),
        }
    )

    _logger.info("【human_review_node】等待律师审核，session_id: %s", session_id)

    return state


def _calculate_coverage_rate(state: ConsultationState) -> float:
    """计算当前事实覆盖度。

    Args:
        state: 当前咨询状态

    Returns:
        覆盖度百分比 (0.0 - 1.0)
    """
    facts_structured = state.get("facts_structured", {})
    applied_laws = state.get("applied_laws", [])

    if not applied_laws:
        return 0.0

    total_elements = 0
    covered_elements = 0

    for law in applied_laws:
        elements = law.get("elements", [])
        total_elements += len(elements)

        for element in elements:
            if isinstance(element, dict):
                element_key = element.get("key", element.get("name", ""))
            else:
                element_key = str(element)
            fact_value = _get_fact_value(facts_structured, element_key)

            if fact_value is not None and fact_value != "":
                if isinstance(fact_value, list) and len(fact_value) == 0:
                    continue
                covered_elements += 1

    if total_elements == 0:
        return 0.0

    return covered_elements / total_elements


def _get_fact_value(facts_structured: Dict[str, Any], key: str) -> Any:
    """从结构化事实中获取指定键的值。

    Args:
        facts_structured: 结构化事实数据
        key: 要获取的键名

    Returns:
        键对应的值，如果不存在返回 None
    """
    key_mapping = {
        "time": "incident_time",
        "location": "incident_location",
        "parties": "parties",
        "behavior": "behavior_sequence",
        "consequence": "consequence",
        "evidence": "evidence_mentioned",
        "arrest": "arrest_status",
        "surrender": "surrender",
        "forgiveness": "victim_forgiveness",
        "record": "prior_record",
    }

    mapped_key = key_mapping.get(key, key)
    return facts_structured.get(mapped_key)


class ConsultationOrchestrator:
    """LangGraph StateGraph wrapper for the complete multi-agent consultation workflow.

    工作流拓扑：
        START → Receptionist → [consent_given?]
                                   ├── True  → FactDigger → [coverage?]
                                   │                             ├── >= 80% → RiskAssessor → ServicePlanner → HumanReview
                                   │                             │                         ↓                ↓
                                   │                             │                    [lawyer_decision]
                                   │                             │                         ↓
                                   │                             ├── < 80%  → FactDigger (自循环)
                                   │                             └── alert → HumanAlert → END
                                   └── False → END
    """

    _workflow: Optional[StateGraph] = None
    _compiled: Optional[Any] = None

    def __init__(self):
        self._logger = get_logger("Orchestrator")
        self._active_sessions: Dict[str, ConsultationState] = {}
        self._workflow = None
        self._compiled = None

    def _build_workflow(self) -> StateGraph:
        """构建工作流 DAG，包含所有 Agent 节点和条件边。

        Returns:
            配置完成的 StateGraph 实例
        """
        workflow = StateGraph(ConsultationState)

        workflow.add_node("receptionist", receptionist_node)
        workflow.add_node("fact_digger", fact_digger_node)
        workflow.add_node("law_ref", law_ref_node)
        workflow.add_node("risk_assessor", risk_assessor_node)
        workflow.add_node("service_planner", service_planner_node)
        workflow.add_node("human_review", human_review_node)
        workflow.add_node("human_alert", human_alert_node)

        workflow.set_entry_point("receptionist")

        workflow.add_conditional_edges("receptionist", check_consent, {"continue": "fact_digger", "end": END})

        workflow.add_edge("fact_digger", "law_ref")

        workflow.add_edge("law_ref", "fact_digger")

        workflow.add_conditional_edges(
            "fact_digger",
            check_facts_sufficient,
            {"complete": "risk_assessor", "loop": "law_ref", "alert": "human_alert", "max_loop": "risk_assessor"},
        )

        workflow.add_edge("risk_assessor", "service_planner")

        workflow.add_edge("service_planner", "human_review")

        workflow.add_conditional_edges(
            "human_review",
            lawyer_decision,
            {"approved": END, "revise_facts": "fact_digger", "revise_risk": "risk_assessor"},
        )

        workflow.add_edge("human_alert", END)

        return workflow

    def _compile_workflow(self) -> None:
        """编译工作流图。"""
        if self._workflow is None:
            self._workflow = self._build_workflow()
        if self._compiled is None:
            self._compiled = self._workflow.compile()
        self._logger.debug("工作流编译完成")

    async def run_node(self, node_name: str, state: ConsultationState) -> ConsultationState:
        """执行单个 Agent 节点。

        Args:
            node_name: 节点名称 (receptionist/fact_digger/law_ref/risk_assessor/service_planner/human_review/human_alert)
            state: 当前咨询状态

        Returns:
            更新后的 ConsultationState

        Raises:
            ValueError: 节点名称无效
        """
        self._compile_workflow()

        node_map = {
            "receptionist": receptionist_node,
            "fact_digger": fact_digger_node,
            "law_ref": law_ref_node,
            "risk_assessor": risk_assessor_node,
            "service_planner": service_planner_node,
            "human_review": human_review_node,
            "human_alert": human_alert_node,
        }

        if node_name not in node_map:
            raise ValueError(f"未知节点: {node_name}")

        session_id = state.get("session_id", "unknown")
        self._logger.info("执行单节点: %s, session_id: %s", node_name, session_id)

        try:
            if node_name == "fact_digger":
                coverage_rate = _calculate_coverage_rate(state)
                state["facts_coverage_rate"] = coverage_rate

            result = await node_map[node_name](state)

            self._logger.info("节点执行完成: %s, session_id: %s", node_name, session_id)
            return result

        except Exception as e:
            self._logger.error("节点执行失败: %s, session_id: %s, error: %s", node_name, session_id, str(e))
            raise

    async def run(self, initial_state: ConsultationState) -> ConsultationState:
        """执行完整的 Agent 工作流。

        Args:
            initial_state: 初始咨询状态，包含 session_id, consent_given 等字段

        Returns:
            所有 Agent 执行完成后的最终状态

        Raises:
            LLMServiceException: LLM 服务异常
            LLMTimeoutException: LLM 调用超时
        """
        self._compile_workflow()

        session_id = initial_state.get("session_id", "unknown")
        consent = initial_state.get("consent_given")

        self._logger.info("开始执行工作流: session_id=%s, consent=%s", session_id, consent)
        self._active_sessions[session_id] = initial_state.copy()

        try:
            result = await self._compiled.ainvoke(initial_state)

            coverage_rate = _calculate_coverage_rate(result)
            result["facts_coverage_rate"] = coverage_rate

        except (LLMServiceException, LLMTimeoutException) as e:
            self._logger.error("工作流异常终止: session_id=%s, error=%s", session_id, e.code.value)
            self._cleanup_session(session_id)
            raise
        except Exception as e:
            self._logger.error("工作流执行失败: session_id=%s, error=%s", session_id, str(e))
            self._cleanup_session(session_id)
            raise

        self._logger.info(
            "工作流执行完成: session_id=%s, current_agent=%s", session_id, result.get("current_agent", "unknown")
        )

        self._update_session_context(session_id, result)

        return result

    def get_session_context(self, session_id: str) -> Optional[ConsultationState]:
        """获取会话上下文。

        Args:
            session_id: 会话 ID

        Returns:
            会话状态，如果不存在返回 None
        """
        return self._active_sessions.get(session_id)

    def update_session_context(self, session_id: str, updates: ConsultationState) -> bool:
        """更新会话上下文。

        Args:
            session_id: 会话 ID
            updates: 要更新的字段

        Returns:
            更新是否成功
        """
        if session_id not in self._active_sessions:
            self._logger.warning("会话不存在: %s", session_id)
            return False

        self._active_sessions[session_id].update(updates)
        self._logger.debug("会话上下文已更新: %s", session_id)
        return True

    def _update_session_context(self, session_id: str, state: ConsultationState) -> None:
        """更新会话上下文（内部使用）。

        Args:
            session_id: 会话 ID
            state: 当前状态
        """
        self.update_session_context(session_id, state)

    def _cleanup_session(self, session_id: str) -> None:
        """清理会话上下文。

        Args:
            session_id: 会话 ID
        """
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
            self._logger.debug("会话上下文已清理: %s", session_id)

    def get_active_sessions(self) -> Dict[str, ConsultationState]:
        """获取所有活跃会话。

        Returns:
            活跃会话字典
        """
        return self._active_sessions.copy()

    async def process_lawyer_feedback(
        self, session_id: str, decision: str, feedback: Optional[str] = None
    ) -> ConsultationState:
        """处理律师反馈。

        Args:
            session_id: 会话 ID
            decision: 律师决策 (approved/revise_facts/revise_risk)
            feedback: 律师反馈内容

        Returns:
            更新后的状态
        """
        self._logger.info("处理律师反馈: session_id=%s, decision=%s", session_id, decision)

        state = self.get_session_context(session_id)
        if not state:
            raise ValueError(f"会话不存在: {session_id}")

        state["lawyer_decision"] = decision
        state["lawyer_feedback"] = feedback
        state["awaiting_lawyer_review"] = False

        self.update_session_context(session_id, state)

        return state


orchestrator = ConsultationOrchestrator()


if __name__ == "__main__":
    print("Orchestrator 模块加载成功")
    import asyncio

    async def test_workflow():
        test_state: ConsultationState = {
            "session_id": "test_session",
            "consultation_id": "test_consultation",
            "user_id": "test_user",
            "consent_given": True,
            "user_type": "suspect",
            "facts_raw": [],
            "facts_structured": {},
            "applied_laws": [],
            "pending_questions": [],
            "alert_triggered": False,
            "conversation_history": [],
        }

        result = await orchestrator.run(test_state)
        print(f"测试完成，最终节点: {result.get('current_agent', 'unknown')}")

    asyncio.run(test_workflow())
