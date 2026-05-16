from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors.exceptions import AppException
from app.errors.handlers import (
    app_exception_handler,
    validation_exception_handler,
    fallback_exception_handler,
)
from app.utils.logger import get_logger

_logger = get_logger("ErrorHandlers")


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application.

    Three-tier coverage:
        1. AppException      → custom status code + error envelope
        2. RequestValidationError → 422 + VALIDATION_ERROR
        3. Exception (catch-all)  → 500 + INTERNAL_ERROR

    Call once during app startup, after all routers are included.
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, fallback_exception_handler)

    _logger.info("Exception handlers registered")
