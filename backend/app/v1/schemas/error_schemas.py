from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Single error entry with machine-readable code and human-readable message."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standardized error envelope returned by all exception handlers.

    Matches the format required by encoding rules:
        {"error": {"code": "...", "message": "..."}}
    """

    error: ErrorDetail
