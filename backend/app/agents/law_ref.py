from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.state.consultation_state import ConsultationState


async def law_ref_node(state: "ConsultationState") -> "ConsultationState":
    return state
