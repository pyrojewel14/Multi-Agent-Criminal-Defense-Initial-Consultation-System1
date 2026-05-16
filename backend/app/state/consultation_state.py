from typing import TypedDict, List


class ConsultationState(TypedDict):
    """Global state object shared across all agents in the LangGraph pipeline"""

    session_id: str
    user_type: str  # suspect / victim / family
    consent_given: bool
    facts_raw: List[str]  # raw user narrative paragraphs
    facts_structured: dict  # structured case facts extracted via LLM Function Calling
    applied_laws: List[dict]  # LawRef retrieval results: charges, articles, cases
    current_agent: str  # name of the currently active agent
    pending_questions: List[str]  # follow-up questions yet to be asked
    alert_triggered: bool  # True when high-risk statement detected
    final_output: str
