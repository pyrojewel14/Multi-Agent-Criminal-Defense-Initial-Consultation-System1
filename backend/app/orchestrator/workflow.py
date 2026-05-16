from langgraph.graph import StateGraph, END

from app.state.consultation_state import ConsultationState
from app.agents.receptionist import receptionist_node
from app.agents.law_ref import law_ref_node


def check_consent(state: ConsultationState) -> str:
    if state.get("consent_given"):
        return "continue"
    return "end"


def create_workflow() -> StateGraph:
    workflow = StateGraph(ConsultationState)

    workflow.add_node("receptionist", receptionist_node)
    workflow.add_node("law_ref", law_ref_node)

    workflow.set_entry_point("receptionist")

    workflow.add_conditional_edges("receptionist", check_consent, {
        "continue": "law_ref",
        "end": END
    })
    workflow.add_edge("law_ref", END)

    return workflow


async def run_workflow(initial_state: ConsultationState) -> ConsultationState:
    workflow = create_workflow()
    app = workflow.compile()
    result = await app.ainvoke(initial_state)
    return result
