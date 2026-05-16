from typing import TYPE_CHECKING

from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.state.consultation_state import ConsultationState

_logger = get_logger("Receptionist")


async def receptionist_node(state: "ConsultationState") -> "ConsultationState":
    """MVP placeholder — greets the client, verifies identity, and obtains
    privacy consent before handing off to LawRef.

    Args:
        state: Current ConsultationState with user message in facts_raw.

    Returns:
        Updated state with user_type, consent_given, and final_output set.
    """
    _logger.debug("Receptionist node called (stub)")
    return state
