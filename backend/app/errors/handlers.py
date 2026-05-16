from fastapi import Request
from fastapi.responses import JSONResponse

from app.errors.codes import ErrorCode
from app.errors.exceptions import AppException
from app.utils.logger import get_logger

_logger = get_logger("ErrorHandlers")


async def app_exception_handler(
    request: Request, exc: AppException
) -> JSONResponse:
    """Handle all AppException subclasses with a standardized error envelope.

    Maps the exception's code + message to the format:
        {"error": {"code": "...", "message": "..."}}
    """
    _logger.warning(
        "AppException: code=%s status=%d path=%s",
        exc.code.value,
        exc.status_code,
        request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code.value,
                "message": exc.message,
            }
        },
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Handle Pydantic/FastAPI request validation errors (422).

    Registered for RequestValidationError; logs which fields failed.
    """
    from fastapi.exceptions import RequestValidationError

    if isinstance(exc, RequestValidationError):
        _logger.warning(
            "Validation error on %s: %s",
            request.url.path,
            exc.errors(),
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "请求参数校验失败",
            }
        },
    )


async def fallback_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Returns 500 with a generic message; the full traceback is logged
    but never exposed to the client.
    """
    import traceback

    _logger.error(
        "Unhandled exception on %s: %s\n%s",
        request.url.path,
        str(exc),
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "系统内部错误，请稍后重试",
            }
        },
    )
