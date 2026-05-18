from app.errors.codes import ErrorCode
from app.utils.logger import get_logger


class AppException(Exception):
    """Base exception for all application-level errors.

    Automatically logs at ERROR level on instantiation. Subclasses declare
    static class attributes for code, status_code, and message; the base
    __init__ picks them up by default but allows per-instance overrides.

    Attributes:
        code: Machine-readable error code (ErrorCode enum).
        status_code: HTTP status code to return to the client.
        message: Human-safe message exposed to the client.
        detail: Internal diagnostic string (not exposed to the client).
    """

    code: ErrorCode
    status_code: int
    message: str

    def __init__(
        self,
        detail: str | None = None,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        message: str | None = None,
    ):
        self.code = code or self.__class__.code
        self.status_code = status_code or self.__class__.status_code
        self.message = message or self.__class__.message
        self.detail = detail

        _logger = get_logger("AppException")
        _logger.error(
            "[%s] %s | status=%d detail=%s",
            self.code.value,
            self.message,
            self.status_code,
            self.detail or "-",
        )
        super().__init__(self.message)


class ConsentRequiredException(AppException):
    """Raised when a client attempts to proceed without privacy consent."""

    code = ErrorCode.CONSENT_REQUIRED
    status_code = 403
    message = "请先完成隐私条款确认"

    def __init__(self, session_id: str):
        super().__init__(detail=f"Consent not given for session: {session_id}")


class HighRiskAlertException(AppException):
    """Raised when a high-risk statement (self-incrimination, etc.) is detected."""

    code = ErrorCode.HIGH_RISK_ALERT
    status_code = 403
    message = "为保护您的权益，此部分内容建议直接与律师单独沟通"

    def __init__(self, session_id: str, risk_detail: str = ""):
        super().__init__(detail=f"High-risk statement in session {session_id}: {risk_detail}")


class LawRetrievalFailedException(AppException):
    """Raised when the law knowledge base retrieval fails."""

    code = ErrorCode.LAW_RETRIEVAL_FAILED
    status_code = 502
    message = "法条检索服务暂不可用，请稍后重试"

    def __init__(self, detail: str = ""):
        super().__init__(detail=detail)


class LLMServiceException(AppException):
    """Raised when the upstream LLM API returns an error."""

    code = ErrorCode.LLM_SERVICE_ERROR
    status_code = 502
    message = "AI 服务暂不可用，请稍后重试"

    def __init__(self, detail: str = ""):
        super().__init__(detail=detail)


class LLMTimeoutException(AppException):
    """Raised when the upstream LLM API times out."""

    code = ErrorCode.LLM_TIMEOUT
    status_code = 504
    message = "AI 服务响应超时，请稍后重试"

    def __init__(self, detail: str = ""):
        super().__init__(detail=detail)


class UnauthorizedException(AppException):
    """Raised when the JWT token is missing, invalid, or expired."""

    code = ErrorCode.UNAUTHORIZED
    status_code = 401
    message = "身份验证失败，请重新登录"

    def __init__(self, detail: str = ""):
        super().__init__(detail=detail)
