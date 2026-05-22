import json
from typing import TYPE_CHECKING, Any, Dict, List

from app.security.disclaimer import disclaimer
from app.utils.llm_gateway import llm_gateway
from app.utils.logger import get_logger
from app.utils.prompt_loader import prompt_loader

if TYPE_CHECKING:
    from app.state.consultation_state import ConsultationState

DEFAULT_SERVICE_PLANNER_PROMPT = """
# 服务方案 Agent 提示词

你是刑事辩护服务规划专家，负责基于风险评估结果生成个性化服务方案和初期咨询报告。

## 核心职责

### 1. 紧急行动建议
基于风险评估，识别需要立即采取的行动：
- 立即行动（24小时内）：立即会见、申请取保、固定有利证据
- 短期行动（1周内）：收集不在场证明、获取谅解书
- 后续行动：辩护策略制定

### 2. 辩护策略概览
- 无罪辩护方向
- 罪轻辩护方向
- 认罪认罚方向

### 3. 律师服务阶段
- 侦查阶段工作内容
- 审查起诉阶段工作内容
- 审判阶段工作内容
- 二审/执行阶段（如需要）

### 4. 费用结构
- 区间报价（符合律协指导标准）
- 注明"具体费用在委托合同中约定"
- 分阶段报价

### 5. 《初期咨询报告》生成
生成 Markdown 格式的完整报告草案，包含所有分析内容。

## 输出要求
1. 所有输出必须包含明确的免责声明前缀："本内容为智能辅助生成，仅供参考，待律师确认后生效。"
2. 费用报价必须符合当地律师协会指导标准
3. 严禁承诺具体案件结果
4. 服务内容必须清晰、具体、可操作

## 报告格式
生成完整的《刑事辩护初期咨询报告》Markdown 文档，包含：
- 案件基本信息
- 事实摘要
- 法律分析
- 风险评估
- 紧急行动建议
- 服务方案建议
- 费用结构
- 下一步建议
- 联系方式
- 重要提示
"""

_logger = get_logger("Agent.ServicePlanner")


async def service_planner_node(state: "ConsultationState") -> "ConsultationState":
    """ServicePlanner Agent 节点函数

    基于风险评估生成服务方案和《初期咨询报告》草案

    Args:
        state: 当前 ConsultationState

    Returns:
        更新后的 ConsultationState
    """
    _logger.info("【service_planner_node】开始生成服务方案")

    try:
        # 提取关键信息用于生成服务方案
        facts_structured = state.get("facts_structured", {})
        applied_laws = state.get("applied_laws", [])
        risk_assessment = state.get("risk_assessment", {})

        # 构建用户消息，包含案件信息
        user_message = _build_service_request_message(
            facts_structured=facts_structured,
            applied_laws=applied_laws,
            risk_assessment=risk_assessment,
            conversation_history=state.get("conversation_history", []),
        )

        # 加载 ServicePlanner 提示词
        system_prompt = _load_service_planner_prompt()

        # 调用 LLM 生成服务方案和报告草案
        _logger.debug("【service_planner_node】调用 LLM 生成服务方案")
        response_content = await llm_gateway.generate(
            system_prompt=system_prompt, user_message=user_message, temperature=0.1, is_legal=False
        )

        # 注入免责声明
        response_content = disclaimer.inject(response_content)

        # 解析 LLM 响应，提取各部分内容
        parsed_response = _parse_llm_response(response_content)

        # 更新状态
        state["service_plan"] = parsed_response.get("service_plan", {})
        state["report_draft"] = parsed_response.get("report_draft", response_content)
        state["lawyer_review_needed"] = True
        state["current_agent"] = "HumanReview"

        # 更新对话历史
        state["conversation_history"] = state.get("conversation_history", [])
        state["conversation_history"].append(
            {
                "agent": "ServicePlanner",
                "action": "generate_service_plan",
                "timestamp": _get_current_timestamp(),
                "summary": "生成服务方案和初期咨询报告草案",
            }
        )

        _logger.info("【service_planner_node】服务方案生成完成，等待律师审核")

    except Exception as e:
        _logger.error("【service_planner_node】生成服务方案时发生错误: %s", str(e))
        raise

    return state


def _build_service_request_message(
    facts_structured: Dict[str, Any], applied_laws: List[Dict[str, Any]], risk_assessment: Dict[str, Any], conversation_history: List[Dict[str, Any]]
) -> str:
    """构建服务方案请求消息

    Args:
        facts_structured: 结构化案件事实
        applied_laws: 适用的法律法规
        risk_assessment: 风险评估结果
        conversation_history: 对话历史

    Returns:
        格式化的用户消息
    """
    message_parts = []

    # 添加案件基本信息
    message_parts.append("【案件基本信息】")
    message_parts.append(f"结构化事实: {json.dumps(facts_structured, ensure_ascii=False)}")
    message_parts.append("")

    # 添加适用法律
    message_parts.append("【适用法律法规】")
    message_parts.append(f"法律法规: {json.dumps(applied_laws, ensure_ascii=False)}")
    message_parts.append("")

    # 添加风险评估
    message_parts.append("【风险评估结果】")
    message_parts.append(f"风险评估: {json.dumps(risk_assessment, ensure_ascii=False)}")
    message_parts.append("")

    # 添加对话历史摘要
    if conversation_history:
        message_parts.append("【对话历史摘要】")
        for idx, entry in enumerate(conversation_history[-5:], 1):
            agent = entry.get("agent", "未知")
            summary = entry.get("summary", "无描述")
            message_parts.append(f"{idx}. [{agent}] {summary}")
        message_parts.append("")

    # 添加服务方案请求
    message_parts.append("【服务方案请求】")
    message_parts.append("请基于以上信息，生成完整的律师服务方案和初期咨询报告草案，包括：")
    message_parts.append("1. 紧急行动建议（立即行动、短期行动、后续行动）")
    message_parts.append("2. 辩护策略概览（无罪辩护、罪轻辩护、认罪认罚）")
    message_parts.append("3. 律师服务阶段及工作内容")
    message_parts.append("4. 费用结构（符合律协指导标准）")
    message_parts.append("5. 《初期咨询报告》Markdown 格式草案")

    return "\n".join(message_parts)


def _load_service_planner_prompt() -> str:
    """加载 ServicePlanner 提示词

    Returns:
        提示词文本
    """
    try:
        return prompt_loader.load("service_planner")
    except KeyError:
        _logger.warning("【_load_service_planner_prompt】未找到 service_planner 提示词，使用默认提示词")
        return _get_default_service_planner_prompt()


def _get_default_service_planner_prompt() -> str:
    """获取默认的 ServicePlanner 提示词

    Returns:
        默认提示词文本
    """
    return DEFAULT_SERVICE_PLANNER_PROMPT


def _parse_llm_response(response_content: str) -> Dict[str, Any]:
    """解析 LLM 响应内容

    Args:
        response_content: LLM 返回的原始内容

    Returns:
        解析后的结构化数据
    """
    result = {"service_plan": {}, "report_draft": response_content}

    try:
        # 尝试从响应中提取服务计划
        service_plan_start = response_content.find("【服务方案")
        report_start = response_content.find("# 刑事辩护初期咨询报告")

        if service_plan_start != -1 and report_start != -1:
            # 分离服务方案和报告
            service_plan_content = response_content[service_plan_start:report_start]
            report_content = response_content[report_start:]

            # 解析服务计划结构
            result["service_plan"] = _extract_service_plan_structure(service_plan_content)
            result["report_draft"] = report_content
        elif report_start != -1:
            # 只有报告内容
            result["report_draft"] = response_content[report_start:]
        else:
            # 整个内容作为报告
            result["report_draft"] = response_content

    except Exception as e:
        _logger.warning("【_parse_llm_response】解析响应时发生错误: %s", str(e))
        result["report_draft"] = response_content

    return result


def _extract_service_plan_structure(service_plan_content: str) -> Dict[str, Any]:
    """提取服务计划结构化信息

    Args:
        service_plan_content: 服务计划文本内容

    Returns:
        结构化的服务计划
    """
    service_plan = {
        "urgent_actions": {"immediate": [], "short_term": [], "follow_up": []},
        "defense_strategies": {"primary": "", "alternatives": []},
        "service_phases": [],
        "fee_structure": {"recommended_plan": "", "total_fee_range": "", "breakdown": {}},
    }

    try:
        lines = service_plan_content.split("\n")
        current_section = None

        for line in lines:
            line = line.strip()

            # 检测紧急行动部分
            if "立即行动" in line or "🔴" in line:
                current_section = "immediate"
            elif "短期行动" in line or "🟡" in line:
                current_section = "short_term"
            elif "后续行动" in line or "🔵" in line:
                current_section = "follow_up"

            # 检测辩护策略部分
            elif "主要辩护策略" in line or "策略类型" in line:
                current_section = "defense_primary"
            elif "备选辩护策略" in line:
                current_section = "defense_alternative"

            # 检测费用部分
            elif "推荐方案" in line or "全程委托" in line:
                current_section = "fee_recommended"

            # 提取具体内容
            if line.startswith("**") and line.endswith("**"):
                action_text = line.strip("*").strip()
                if current_section == "immediate":
                    service_plan["urgent_actions"]["immediate"].append(action_text)
                elif current_section == "short_term":
                    service_plan["urgent_actions"]["short_term"].append(action_text)
                elif current_section == "follow_up":
                    service_plan["urgent_actions"]["follow_up"].append(action_text)

    except Exception as e:
        _logger.warning("【_extract_service_plan_structure】提取服务计划结构时发生错误: %s", str(e))

    return service_plan


def _get_current_timestamp() -> str:
    """获取当前时间戳

    Returns:
        ISO 格式的时间字符串
    """
    from datetime import datetime

    return datetime.now().isoformat()

