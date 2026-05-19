from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.security.disclaimer import disclaimer
from app.utils.factory import chat_model_factory
from app.utils.llm_gateway import llm_gateway
from app.utils.logger import get_logger
from app.utils.prompt_loader import prompt_loader

if TYPE_CHECKING:
    from app.state.consultation_state import ConsultationState

_logger = get_logger("Agent.FactDigger")

COVERAGE_THRESHOLD = 0.8

EXTRACT_CASE_FACTS_PROMPT = """从咨询者描述中提取刑事案件关键事实要素。

请提取以下字段：
- incident_time: 事件发生时间
- incident_location: 事件发生地点（已脱敏）
- parties: 当事人列表（包含 role, name, relationship）
- behavior_sequence: 行为时间序列（包含 time, actor, action, method, target）
- consequence: 后果描述
- evidence_mentioned: 提到的证据线索
- arrest_status: 当前羁押状态
- surrender: 是否自首
- victim_forgiveness: 被害人是否谅解
- prior_record: 是否有前科劣迹

如果某字段信息不明确，设为 null。"""

DEFAULT_FOLLOW_UP_PROMPT = """你是一个刑事案件事实挖掘专家。
根据以下缺失的构成要件，生成追问问题。
要求：
1. 追问必须是开放性的，不能诱导用户做出特定回答
2. 禁止假设性提问，不假设用户做过或没做过某事
3. 保持客观性，不评判用户行为的对错
4. 问题要简洁、清晰

请生成 JSON 格式的问题列表。"""

DEFAULT_SUMMARY_PROMPT = """你是一个刑事案件事实整理专家。
根据以下结构化事实和原始描述，生成一份清晰、准确的案件事实摘要。
要求：
1. 按时间顺序整理事件经过
2. 突出关键情节和重要细节
3. 保持客观、中性的表述
4. 使用简洁的语言

请生成 Markdown 格式的事实摘要。"""

DEFAULT_FIRST_PROMPT = """请按以下时间线结构描述事件经过：

1. 【事前】- 事件发生前的背景
   - 什么情况下发生的？
   - 当事人之间的关系是什么？

2. 【事发】- 事件发生时的经过
   - 具体发生了什么？
   - 在什么时间、地点发生的？
   - 有哪些人参与？

3. 【事中】- 事件进行中的关键情节
   - 是否有暴力、威胁等行为？
   - 是否有财产损失或人身伤害？
   - 当事人各方分别做了什么？

4. 【事后】- 事件发生后的发展
   - 事后各方有何反应？
   - 是否有人报警？
   - 公安或其他部门是否介入？"""


def _load_follow_up_prompt() -> str:
    """加载追问提示词"""
    try:
        return prompt_loader.load("fact_digger_prompt")
    except KeyError:
        return DEFAULT_FOLLOW_UP_PROMPT


def _load_summary_prompt() -> str:
    """加载摘要提示词"""
    try:
        return prompt_loader.load("fact_digger_summary_prompt")
    except KeyError:
        return DEFAULT_SUMMARY_PROMPT


@tool
def extract_case_facts(
    incident_time: Optional[str] = None,
    incident_location: Optional[str] = None,
    parties: Optional[List[Dict[str, Any]]] = None,
    behavior_sequence: Optional[List[Dict[str, Any]]] = None,
    consequence: Optional[str] = None,
    evidence_mentioned: Optional[List[Dict[str, Any]]] = None,
    arrest_status: Optional[str] = None,
    surrender: Optional[bool] = None,
    victim_forgiveness: Optional[bool] = None,
    prior_record: Optional[bool] = None,
) -> Dict[str, Any]:
    """从咨询者描述中提取刑事案件关键事实要素。

    Args:
        incident_time: 事件发生时间，格式：YYYY-MM-DD 或 相对时间
        incident_location: 事件发生地点（已脱敏）
        parties: 当事人列表
        behavior_sequence: 行为时间序列
        consequence: 后果描述
        evidence_mentioned: 提到的证据线索
        arrest_status: 当前羁押状态
        surrender: 是否自首
        victim_forgiveness: 被害人是否谅解
        prior_record: 是否有前科劣迹

    Returns:
        包含所有提取字段的字典
    """
    return {
        "incident_time": incident_time,
        "incident_location": incident_location,
        "parties": parties or [],
        "behavior_sequence": behavior_sequence or [],
        "consequence": consequence,
        "evidence_mentioned": evidence_mentioned or [],
        "arrest_status": arrest_status,
        "surrender": surrender,
        "victim_forgiveness": victim_forgiveness,
        "prior_record": prior_record,
    }


async def _analyze_coverage(facts_structured: Dict[str, Any], applied_laws: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析构成要件覆盖度。

    Args:
        facts_structured: 结构化事实数据
        applied_laws: 适用的法律条款列表

    Returns:
        覆盖度分析结果字典
    """
    if not applied_laws:
        return {
            "total_elements": 0,
            "covered_elements": 0,
            "coverage_rate": 0.0,
            "missing_elements": [],
            "weak_elements": [],
        }

    covered_elements = []
    missing_elements = []
    weak_elements = []

    for law in applied_laws:
        required_elements = law.get("elements", [])

        for element in required_elements:
            if isinstance(element, dict):
                element_name = element.get("name", "")
                element_key = element.get("key", element_name)
            else:
                element_name = str(element)
                element_key = str(element)

            fact_value = _get_fact_value(facts_structured, element_key)

            if fact_value is not None and fact_value != "":
                covered_elements.append(element_name)

                if isinstance(fact_value, list) and len(fact_value) == 0:
                    weak_elements.append(element_name)
                elif isinstance(fact_value, bool) and not fact_value:
                    weak_elements.append(element_name)
            else:
                missing_elements.append(element_name)

    total_elements = len(covered_elements) + len(missing_elements)
    coverage_rate = len(covered_elements) / total_elements if total_elements > 0 else 0.0

    return {
        "total_elements": total_elements,
        "covered_elements": len(covered_elements),
        "coverage_rate": coverage_rate,
        "missing_elements": missing_elements,
        "weak_elements": weak_elements,
    }


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


async def _generate_follow_up_questions(missing_elements: List[str], facts_structured: Dict[str, Any]) -> List[str]:
    """根据缺失的构成要件生成追问问题。

    Args:
        missing_elements: 缺失的构成要件列表
        facts_structured: 当前结构化事实数据

    Returns:
        追问问题列表
    """
    if not missing_elements:
        return []

    system_prompt = _load_follow_up_prompt()

    user_message_parts = [
        "当前已收集的事实：",
        str(facts_structured),
        "",
        "缺失的构成要件：",
        str(missing_elements),
        "",
        "请针对每个缺失的构成要件生成一个追问问题，返回格式：",
        '{"questions": ["问题1", "问题2", ...]}',
    ]
    user_message = "\n".join(user_message_parts)

    try:
        response = await llm_gateway.generate(system_prompt=system_prompt, user_message=user_message, temperature=0.1)

        import json

        start_idx = response.find("{")
        end_idx = response.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)
            return data.get("questions", [])
    except Exception as e:
        _logger.error("【_generate_follow_up_questions】生成追问失败: %s", e)

    return []


async def _generate_fact_summary(facts_structured: Dict[str, Any], facts_raw: List[str]) -> str:
    """生成事实摘要。

    Args:
        facts_structured: 结构化事实数据
        facts_raw: 原始用户输入

    Returns:
        生成的事实摘要
    """
    system_prompt = _load_summary_prompt()

    user_message_parts = [
        "结构化事实：",
        str(facts_structured),
        "",
        "原始用户描述：",
        "\n".join(facts_raw),
        "",
        "请生成案件事实摘要。",
    ]
    user_message = "\n".join(user_message_parts)

    try:
        summary = await llm_gateway.generate(system_prompt=system_prompt, user_message=user_message, temperature=0.1)
        return summary
    except Exception as e:
        _logger.error("【_generate_fact_summary】生成事实摘要失败: %s", e)
        return ""


async def _extract_structured_facts(facts_raw: List[str]) -> Dict[str, Any]:
    """使用 LLM Function Calling 提取结构化事实。

    Args:
        facts_raw: 原始用户输入列表

    Returns:
        结构化事实字典
    """
    model = chat_model_factory.create_model(temperature=0.1)
    model_with_tools = model.bind_tools([extract_case_facts])

    combined_facts = "\n".join([f"- {fact}" for fact in facts_raw])

    messages = [
        SystemMessage(content=EXTRACT_CASE_FACTS_PROMPT),
        HumanMessage(content=f"请从以下描述中提取案件事实要素：\n\n{combined_facts}"),
    ]

    try:
        response = await model_with_tools.ainvoke(messages)

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.get("name") == "extract_case_facts":
                    return tool_call.get("args", {})

        if hasattr(response, "additional_kwargs"):
            function_call = response.additional_kwargs.get("function_call")
            if function_call:
                import json

                args_str = function_call.get("arguments", "{}")
                return json.loads(args_str)

        return {}
    except Exception as e:
        _logger.error("【_extract_structured_facts】Function Calling 提取失败: %s", e)
        return {}


async def fact_digger_node(state: "ConsultationState") -> "ConsultationState":
    """FactDigger Agent 节点函数

    处理事实收集、结构化提取和追问逻辑
    与 LawRef 双向交互：当 applied_laws 有数据时分析覆盖度

    Args:
        state: 当前 ConsultationState

    Returns:
        更新后的 ConsultationState
    """
    _logger.info("【fact_digger_node】FactDigger 节点开始执行")

    facts_raw = state.get("facts_raw", [])
    facts_structured = state.get("facts_structured", {})
    applied_laws = state.get("applied_laws", [])
    pending_questions = state.get("pending_questions", [])
    conversation_history = state.get("conversation_history", [])

    user_input = state.get("current_input", "")

    if not facts_raw and not user_input:
        response_text = disclaimer.inject(DEFAULT_FIRST_PROMPT)

        conversation_history.append({"agent": "FactDigger", "role": "assistant", "content": response_text})

        state["current_agent"] = "FactDigger"
        state["conversation_history"] = conversation_history
        state["final_output"] = response_text
        state["facts_coverage_rate"] = 0.0

        _logger.info("【fact_digger_node】发送首次引导语")
        return state

    if user_input:
        facts_raw.append(user_input)
        _logger.debug("【fact_digger_node】追加用户输入到 facts_raw，当前共 %d 条", len(facts_raw))

    facts_structured = await _extract_structured_facts(facts_raw)
    _logger.debug("【fact_digger_node】提取结构化事实完成")

    state["facts_structured"] = facts_structured
    state["facts_raw"] = facts_raw

    if not applied_laws:
        _logger.info("【fact_digger_node】等待 LawRef 返回法条信息")
        state["current_agent"] = "FactDigger"
        state["conversation_history"] = conversation_history
        return state

    coverage_analysis = await _analyze_coverage(facts_structured, applied_laws)
    coverage_rate = coverage_analysis.get("coverage_rate", 0.0)
    state["facts_coverage_rate"] = coverage_rate

    _logger.info(
        "【fact_digger_node】构成要件覆盖度: %.2f (%d/%d)",
        coverage_rate,
        coverage_analysis.get("covered_elements", 0),
        coverage_analysis.get("total_elements", 0),
    )

    if coverage_rate < COVERAGE_THRESHOLD:
        missing_elements = coverage_analysis.get("missing_elements", [])
        new_questions = await _generate_follow_up_questions(missing_elements, facts_structured)

        pending_questions.extend(new_questions)

        response_text = "为了更准确地分析案件，请您补充以下信息：\n\n"
        for i, question in enumerate(new_questions, 1):
            response_text += f"{i}. {question}\n"

        response_text = disclaimer.inject(response_text)

        conversation_history.append({"agent": "FactDigger", "role": "assistant", "content": response_text})

        state["pending_questions"] = pending_questions
        state["final_output"] = response_text
        state["current_agent"] = "FactDigger"

        _logger.info("【fact_digger_node】生成追问 %d 个，覆盖度不足", len(new_questions))
    else:
        summary = await _generate_fact_summary(facts_structured, facts_raw)

        response_text_parts = [
            "## 案件事实摘要",
            "",
            "请确认以下内容是否准确：",
            "",
            summary,
            "",
            "如有不准确之处，请修正。",
        ]
        response_text = "\n".join(response_text_parts)
        response_text = disclaimer.inject(response_text)

        conversation_history.append({"agent": "FactDigger", "role": "assistant", "content": response_text})

        state["final_output"] = response_text
        state["current_agent"] = "RiskAssessor"

        _logger.info("【fact_digger_node】生成事实摘要，覆盖度已达标，跳转 RiskAssessor")

    state["conversation_history"] = conversation_history

    _logger.info("【fact_digger_node】FactDigger 节点执行完成")
    return state
