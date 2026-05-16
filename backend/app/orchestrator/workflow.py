from langgraph.graph import StateGraph, END

from app.state.consultation_state import ConsultationState
from app.agents.receptionist import receptionist_node
from app.agents.law_ref import law_ref_node
from app.utils.logger import get_logger


def check_consent(state: ConsultationState) -> str:
    """LangGraph conditional edge router — branch on consent_given flag.

    Returns 'continue' to proceed to LawRef, 'end' to terminate immediately.
    """
    if state.get("consent_given"):
        return "continue"
    return "end"


class ConsultationOrchestrator:
    """LangGraph StateGraph wrapper for the MVP two-agent pipeline.

    Workflow topology (built once, reused across sessions):
        START → Receptionist → [consent_given?]
                                  ├── True  → LawRef → END
                                  └── False → END
    """

    def __init__(self):
        self._logger = get_logger("Orchestrator")
        self._logger.info("Building and compiling StateGraph workflow")
        self._workflow = self._build_workflow()
        self._compiled = self._workflow.compile()

    def _build_workflow(self) -> StateGraph:
        """Construct the static DAG of agent nodes and conditional edges."""
        workflow = StateGraph(ConsultationState)

        workflow.add_node("receptionist", receptionist_node)
        workflow.add_node("law_ref", law_ref_node)

        workflow.set_entry_point("receptionist")

        workflow.add_conditional_edges("receptionist", check_consent, {
            "continue": "law_ref",
            "end": END,
        })
        workflow.add_edge("law_ref", END)

        return workflow

    async def run(self, initial_state: ConsultationState) -> ConsultationState:
        """Execute the full agent pipeline for a single session.

        Args:
            initial_state: Populated ConsultationState with at least
                session_id, consent_given, and current user message context.

        Returns:
            The final ConsultationState after all agents have executed.
        """
        session_id = initial_state.get("session_id", "unknown")
        consent = initial_state.get("consent_given")
        self._logger.info(
            "Running workflow: session=%s, consent=%s", session_id, consent
        )
        result = await self._compiled.ainvoke(initial_state)
        self._logger.info(
            "Workflow completed: session=%s, agent=%s",
            session_id,
            result.get("current_agent", "unknown"),
        )
        return result


orchestrator = ConsultationOrchestrator()


if __name__ == "__main__":
    print("Orchestrator is running")
    import asyncio
    asyncio.run(orchestrator.run({"session_id": "test_session", "consent_given": True}))
    print("Orchestrator completed")