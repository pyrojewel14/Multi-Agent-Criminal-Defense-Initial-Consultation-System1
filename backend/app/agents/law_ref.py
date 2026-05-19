import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.security.disclaimer import disclaimer
from app.utils.llm_gateway import llm_gateway
from app.utils.logger import get_logger
from app.utils.prompt_loader import prompt_loader

if TYPE_CHECKING:
    from app.state.consultation_state import ConsultationState

_logger = get_logger("Agent.LawRef")

LAW_KNOWLEDGE_PATH = Path(__file__).parent.parent.parent / "data" / "law_knowledge" / "criminal_law_chapters.json"

DEFAULT_LAW_EXTRACT_PROMPT = """你是一名刑事法律专家，根据用户描述的案件事实和匹配的刑法条文，提取结构化的法律信息。

请分析以下信息并输出 JSON 格式的结构化法律分析：

输出格式：
{
    "charges": [
        {
            "charge_name": "罪名名称",
            "article_number": "法条编号",
            "elements_matched": ["匹配的构成要件"],
            "elements_missing": ["缺失的构成要件"],
            "base_sentence": "基准刑",
            "probability": "high/medium/low"
        }
    ],
    "procedural_notes": ["程序性注意事项"]
}

重要：
1. 只分析匹配度较高的罪名
2. 如果无法确定，明确说明
3. 所有法律引用必须准确
"""


def _load_law_extract_prompt() -> str:
    """加载法条提取提示词"""
    try:
        return prompt_loader.load("lawref_prompt")
    except KeyError:
        return DEFAULT_LAW_EXTRACT_PROMPT


def load_criminal_law_data() -> Dict[str, Any]:
    """加载刑事法律条文数据。

    Returns:
        包含章节和条文数据的字典。如果文件不存在，返回空结构。
        注意：JSON 文件结构为数组，每个元素包含 chapter 和 article 信息。
    """
    try:
        if LAW_KNOWLEDGE_PATH.exists():
            with open(LAW_KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            if isinstance(raw_data, list):
                chapters_dict: Dict[str, List[Dict]] = {}
                for article in raw_data:
                    chapter_name = article.get("chapter", "未分类")
                    if chapter_name not in chapters_dict:
                        chapters_dict[chapter_name] = []
                    chapters_dict[chapter_name].append(
                        {
                            "article_number": article.get("article_number", ""),
                            "title": article.get("title", ""),
                            "content": article.get("content", ""),
                            "elements": article.get("elements", []),
                            "base_sentence": article.get("base_sentence", ""),
                            "charge_tags": article.get("charge_tags", []),
                            "common_keywords": article.get("common_keywords", []),
                        }
                    )

                chapters_list = [
                    {"chapter": chapter_name, "articles": articles} for chapter_name, articles in chapters_dict.items()
                ]

                data = {"chapters": chapters_list}
            else:
                data = raw_data

            _logger.info("【load_criminal_law_data】成功加载法条数据，共 %d 章", len(data.get("chapters", [])))
            return data
        else:
            _logger.warning("【load_criminal_law_data】法条数据文件不存在: %s", LAW_KNOWLEDGE_PATH)
            return {"chapters": []}
    except Exception as e:
        _logger.error("【load_criminal_law_data】加载法条数据失败: %s", str(e))
        return {"chapters": []}


async def search_laws_by_keyword(facts_structured: Dict[str, Any], law_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """通过关键词搜索匹配的刑法条文。

    Args:
        facts_structured: 结构化的事实数据。
        law_data: 刑法条文数据。

    Returns:
        匹配的条文列表。
    """
    behavior_sequence = facts_structured.get("behavior_sequence", [])
    consequence = facts_structured.get("consequence", "")

    search_terms = []
    if isinstance(behavior_sequence, list):
        search_terms.extend(behavior_sequence)
    else:
        search_terms.append(str(behavior_sequence))
    if consequence:
        search_terms.append(str(consequence))

    matched_laws = []
    search_text = " ".join(search_terms).lower()

    for chapter in law_data.get("chapters", []):
        for article in chapter.get("articles", []):
            charge_name = article.get("title", "").lower()
            charge_tags = " ".join(article.get("charge_tags", [])).lower()
            content = article.get("content", "").lower()
            common_keywords = " ".join(article.get("common_keywords", [])).lower()

            relevance_score = 0
            matched_tags = []

            for term in search_terms:
                term_lower = term.lower()
                if term_lower in charge_name:
                    relevance_score += 3
                    matched_tags.append(f"罪名匹配: {term}")
                if term_lower in charge_tags:
                    relevance_score += 2
                    matched_tags.append(f"标签匹配: {term}")
                if term_lower in common_keywords:
                    relevance_score += 1
                    matched_tags.append(f"关键词匹配: {term}")
                if term_lower in content:
                    relevance_score += 0.5

            if relevance_score > 0:
                matched_laws.append(
                    {
                        "article_number": article.get("article_number", ""),
                        "title": article.get("title", ""),
                        "content": article.get("content", ""),
                        "elements": article.get("elements", []),
                        "base_sentence": article.get("base_sentence", ""),
                        "charge_tags": article.get("charge_tags", []),
                        "common_keywords": article.get("common_keywords", []),
                        "chapter": chapter.get("chapter", ""),
                        "relevance_score": relevance_score,
                        "matched_tags": matched_tags,
                    }
                )

    matched_laws.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    _logger.info("【search_laws_by_keyword】关键词匹配找到 %d 条相关法条", len(matched_laws))

    return matched_laws


async def search_laws_by_rag(facts_structured: Dict[str, Any], session_id: str) -> List[Dict[str, Any]]:
    """通过 RAG 向量检索搜索匹配的刑法条文。

    Args:
        facts_structured: 结构化的事实数据。
        session_id: 会话 ID。

    Returns:
        匹配的条文列表。
    """
    try:
        from app.rag.rag_service import RagService

        behavior_sequence = facts_structured.get("behavior_sequence", [])
        consequence = facts_structured.get("consequence", "")

        query_parts = []
        if isinstance(behavior_sequence, list):
            query_parts.extend(behavior_sequence)
        else:
            query_parts.append(str(behavior_sequence))
        if consequence:
            query_parts.append(str(consequence))

        query = " ".join(query_parts)
        if not query.strip():
            query = "刑事犯罪"

        rag_service = RagService(user_id=session_id, include_public=True)
        await rag_service.initialize_retriever(query)

        result = await rag_service.get_documents_and_summary(query)
        documents = result.get("documents", [])

        matched_laws = []
        for doc in documents:
            if isinstance(doc, str):
                doc_content = doc
            elif hasattr(doc, "page_content"):
                doc_content = doc.page_content
            else:
                continue

            matched_laws.append(
                {
                    "article_number": "待确认",
                    "title": "通过 RAG 检索",
                    "content": doc_content[:500],
                    "elements": [],
                    "base_sentence": "待评估",
                    "charge_tags": [],
                    "common_keywords": [],
                    "chapter": "检索结果",
                    "relevance_score": 1.0,
                    "matched_tags": ["RAG 向量检索"],
                }
            )

        _logger.info("【search_laws_by_rag】RAG 检索找到 %d 条相关法条", len(matched_laws))
        return matched_laws

    except Exception as e:
        _logger.error("【search_laws_by_rag】RAG 检索失败: %s", str(e))
        return []


async def extract_structured_laws(
    matched_laws: List[Dict[str, Any]], facts_structured: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """使用 LLM 从匹配的法条中提取结构化信息。

    Args:
        matched_laws: 匹配的条文列表。
        facts_structured: 结构化的事实数据。

    Returns:
        结构化的法律信息列表。
    """
    if not matched_laws:
        return []

    laws_context = []
    for i, law in enumerate(matched_laws[:5], 1):
        law_parts = [
            f"【法条 {i}】",
            f"- 条款: {law.get('article_number', '')}",
            f"- 罪名: {law.get('title', '')}",
            f"- 内容: {law.get('content', '')[:200]}...",
            f"- 构成要件: {', '.join(law.get('elements', []))}",
            f"- 基准刑: {law.get('base_sentence', '')}",
            f"- 标签: {', '.join(law.get('charge_tags', []))}",
        ]
        laws_context.append("\n".join(law_parts))

    context_text = "\n".join(laws_context)

    facts_text = f"""行为描述: {", ".join(facts_structured.get("behavior_sequence", []))}
后果: {facts_structured.get("consequence", "未知")}
"""

    system_prompt = _load_law_extract_prompt()

    user_message_parts = [
        "案件事实：",
        facts_text,
        "",
        "匹配的刑法条文：",
        context_text,
        "",
        "请提取结构化的法律分析。",
    ]
    user_message = "\n".join(user_message_parts)

    try:
        response = await llm_gateway.generate(system_prompt, user_message, is_legal=True)

        import re

        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            structured_result = json.loads(json_match.group())
            _logger.info("【extract_structured_laws】LLM 结构化提取成功")
            return structured_result.get("charges", [])
        else:
            _logger.warning("【extract_structured_laws】LLM 响应中未找到 JSON")
            return []

    except Exception as e:
        _logger.error("【extract_structured_laws】LLM 调用失败: %s", str(e))
        return []


async def law_ref_node(state: "ConsultationState") -> "ConsultationState":
    """LawRef Agent 节点函数 - 法条检索 Agent。

    根据结构化事实检索相关法条，支持：
    1. 静态 JSON 知识库关键词匹配
    2. RAG 向量检索
    3. LLM 结构化信息提取

    Args:
        state: 当前 ConsultationState。

    Returns:
        更新后的 ConsultationState。
    """
    _logger.info("【law_ref_node】LawRef 节点开始执行")

    session_id = state.get("session_id", "unknown")
    facts_structured = state.get("facts_structured", {})

    if not facts_structured:
        _logger.warning("【law_ref_node】facts_structured 为空，跳过法条检索")
        state["applied_laws"] = []
        state["current_agent"] = "LawRef"
        return state

    law_data = load_criminal_law_data()

    matched_laws = []

    if law_data.get("chapters"):
        _logger.info("【law_ref_node】使用静态知识库关键词匹配")
        matched_laws = await search_laws_by_keyword(facts_structured, law_data)

    if len(matched_laws) < 3:
        _logger.info("【law_ref_node】使用 RAG 向量检索补充")
        rag_results = await search_laws_by_rag(facts_structured, session_id)
        for result in rag_results:
            exists = False
            for existing in matched_laws:
                if result.get("title") == existing.get("title"):
                    exists = True
                    break
            if not exists:
                matched_laws.append(result)

    structured_laws = await extract_structured_laws(matched_laws, facts_structured)

    element_to_law_mapping = {}
    if structured_laws:
        applied_laws = []
        for law in structured_laws:
            charge_name = law.get("charge_name", "")
            elements_matched = law.get("elements_matched", [])
            for element in elements_matched:
                if element not in element_to_law_mapping:
                    element_to_law_mapping[element] = {
                        "charge_name": charge_name,
                        "article_number": law.get("article_number", ""),
                        "base_sentence": law.get("base_sentence", ""),
                    }
            applied_laws.append(
                {
                    "charge_name": charge_name,
                    "article_number": law.get("article_number", ""),
                    "elements": elements_matched,
                    "elements_missing": law.get("elements_missing", []),
                    "base_sentence": law.get("base_sentence", ""),
                    "probability": law.get("probability", "medium"),
                }
            )
    else:
        applied_laws = []
        for law in matched_laws[:5]:
            charge_name = law.get("title", "")
            elements = law.get("elements", [])
            for element in elements:
                if element not in element_to_law_mapping:
                    element_to_law_mapping[element] = {
                        "charge_name": charge_name,
                        "article_number": law.get("article_number", ""),
                        "base_sentence": law.get("base_sentence", ""),
                    }
            applied_laws.append(
                {
                    "charge_name": charge_name,
                    "article_number": law.get("article_number", ""),
                    "elements": elements,
                    "base_sentence": law.get("base_sentence", ""),
                    "charge_tags": law.get("charge_tags", []),
                }
            )

    state["applied_laws"] = applied_laws
    state["element_to_law_mapping"] = element_to_law_mapping
    state["current_agent"] = "LawRef"

    if "conversation_history" not in state:
        state["conversation_history"] = []
    state["conversation_history"].append(
        {"agent": "LawRef", "action": "law_search", "matched_count": len(applied_laws), "session_id": session_id}
    )

    _logger.info("【law_ref_node】法条检索完成，找到 %d 个匹配罪名", len(applied_laws))

    return state


if __name__ == "__main__":
    import asyncio

    async def test():
        test_state: ConsultationState = {
            "session_id": "test-001",
            "consent_given": True,
            "user_type": "suspect",
            "facts_raw": [],
            "facts_structured": {"behavior_sequence": ["推", "打"], "consequence": "轻伤"},
            "applied_laws": [],
            "current_agent": "LawRef",
            "pending_questions": [],
            "alert_triggered": False,
            "final_output": "",
            "conversation_history": [],
        }

        result = await law_ref_node(test_state)
        _logger.info("找到 %d 个匹配罪名:", len(result["applied_laws"]))
        for law in result["applied_laws"]:
            _logger.info("  - %s: %s", law.get("charge_name"), law.get("article_number"))

    asyncio.run(test())
