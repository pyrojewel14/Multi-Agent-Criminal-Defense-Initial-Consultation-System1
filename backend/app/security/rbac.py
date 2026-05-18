from functools import wraps
from typing import List, Callable, Optional

from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.security.jwt import decode_token
from app.utils.logger import get_logger

_logger = get_logger("RBAC")

security = HTTPBearer(auto_error=False)


async def get_optional_user_from_header(request: Request) -> Optional[dict]:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.replace("Bearer ", "")
    payload = decode_token(token)
    
    if not payload or payload.get("type") != "access":
        return None
    
    return {
        "user_id": payload.get("sub"),
        "role": payload.get("role"),
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="无效或过期的 Token")
    
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="无效的 Token 类型")
    
    return {
        "user_id": payload.get("sub"),
        "role": payload.get("role"),
    }


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[dict]:
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if not payload or payload.get("type") != "access":
        return None
    
    return {
        "user_id": payload.get("sub"),
        "role": payload.get("role"),
    }


def require_roles(allowed_roles: List[str]):
    async def dependency(user: dict = Depends(get_current_user)):
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，需要角色: {', '.join(allowed_roles)}"
            )
        return user
    return dependency


def require_admin():
    return require_roles(["admin"])


def require_lawyer():
    return require_roles(["admin", "lawyer"])


async def get_user_from_request(request: Request) -> Optional[dict]:
    return getattr(request.state, "user", None)


async def attach_user_to_request(request: Request, call_next):
    user = await get_optional_user_from_header(request)
    if user:
        request.state.user = user
    response = await call_next(request)
    return response


class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    async def __call__(self, user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in self.allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，需要角色: {', '.join(self.allowed_roles)}"
            )
        return user


ADMIN_ROLES = ["admin"]
LAWYER_ROLES = ["lawyer"]
CLIENT_ROLES = ["client"]
ADMIN_LAWYER_ROLES = ["admin", "lawyer"]