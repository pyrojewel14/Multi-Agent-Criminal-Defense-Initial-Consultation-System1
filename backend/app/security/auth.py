from fastapi import Request, Depends

from app.security.session import validate_session
from app.errors.exceptions import UnauthorizedException
from app.utils.logger import get_logger

_logger = get_logger("Auth")

HEADER_SESSION_ID = "X-Session-ID"


async def get_session_id(request: Request) -> str:
    """Extract and validate the session_id from the request header.

    Reads ``X-Session-ID`` header, validates it against the session store,
    and returns the raw session_id string on success.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The validated session_id string.

    Raises:
        UnauthorizedException: If the header is missing or the session is
            invalid / expired.
    """
    session_id = request.headers.get(HEADER_SESSION_ID)

    if not session_id:
        _logger.warning("Missing %s header", HEADER_SESSION_ID)
        raise UnauthorizedException(detail="Missing X-Session-ID header")

    if not await validate_session(session_id):
        _logger.warning("Invalid or expired session: %s", session_id)
        raise UnauthorizedException(detail=f"Invalid or expired session: {session_id}")

    _logger.debug("Session validated: %s", session_id)
    return session_id


async def require_session(
    session_id: str = Depends(get_session_id),
) -> str:
    """FastAPI dependency that enforces session authentication.

    Use as a ``Depends()`` parameter in route handlers.  Returns the
    validated session_id for downstream use.

    Example::

        @router.get("/resource")
        async def get_resource(session_id: str = Depends(require_session)):
            ...

    Args:
        session_id: Injected by ``get_session_id`` dependency.

    Returns:
        The validated session_id.
    """
    return session_id
