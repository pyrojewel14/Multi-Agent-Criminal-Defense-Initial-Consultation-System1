from app.security.config import (
    JWTConfig,
    JWTConfigError,
    get_jwt_config,
    reload_jwt_config,
)
from app.security.disclaimer import DisclaimerService, disclaimer, DISCLAIMER_PREFIX
from app.security.jwt import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expiry,
)
from app.security.rbac import (
    get_current_user,
    get_optional_user,
    require_roles,
    require_admin,
    require_lawyer,
    RoleChecker,
    attach_user_to_request,
    ADMIN_ROLES,
    LAWYER_ROLES,
    CLIENT_ROLES,
    ADMIN_LAWYER_ROLES,
)
from app.security.sensitive_filter import mask_pii, detect_high_risk, sanitize_input

__all__ = [
    "JWTConfig",
    "JWTConfigError",
    "get_jwt_config",
    "reload_jwt_config",
    "DisclaimerService",
    "disclaimer",
    "DISCLAIMER_PREFIX",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_token_expiry",
    "get_current_user",
    "get_optional_user",
    "require_roles",
    "require_admin",
    "require_lawyer",
    "RoleChecker",
    "attach_user_to_request",
    "ADMIN_ROLES",
    "LAWYER_ROLES",
    "CLIENT_ROLES",
    "ADMIN_LAWYER_ROLES",
    "mask_pii",
    "detect_high_risk",
    "sanitize_input",
]
