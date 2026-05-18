from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.models.user import Consultation, User, UserRole
from app.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expiry,
    hash_password,
    verify_password,
)
from app.security.rbac import get_current_user, require_admin
from app.utils.logger import get_logger
from app.v1.schemas.auth_schemas import (
    LawyerListResponse,
    LoginResponse,
    TokenRefreshRequest,
    TokenResponse,
    UserListResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    UserRoleUpdateRequest,
    UserUpdateRequest,
)

_logger = get_logger("Router.Auth")

auth_router = APIRouter(prefix="/auth", tags=["authentication"])


@auth_router.post("/register", status_code=201)
async def register(
    request: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户注册接口。

    Args:
        request: 用户注册请求参数。
        db: 数据库会话。

    Returns:
        注册成功返回用户信息。
    """
    _logger.info("【register】注册请求: username=%s, email=%s", request.username, request.email)

    existing = await db.execute(select(User).where(User.username == request.username))
    if existing.scalar_one_or_none():
        _logger.warning("【register】注册失败: 用户名已存在 username=%s", request.username)
        raise HTTPException(status_code=400, detail="用户名已存在")

    if request.email:
        existing_email = await db.execute(select(User).where(User.email == request.email))
        if existing_email.scalar_one_or_none():
            _logger.warning("【register】注册失败: 邮箱已被使用 email=%s", request.email)
            raise HTTPException(status_code=400, detail="邮箱已被使用")

    user = User(
        username=request.username,
        password_hash=hash_password(request.password),
        email=request.email,
        phone=request.phone,
        real_name=request.real_name,
        role=UserRole.CLIENT,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _logger.info(
        "【register】用户注册成功: username=%s, user_id=%s, role=%s", request.username, user.id, user.role.value
    )

    return success_response(data=UserResponse.model_validate(user), message="注册成功")


@auth_router.post("/login")
async def login(
    request: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户登录接口。

    Args:
        request: 用户登录请求参数。
        db: 数据库会话。

    Returns:
        登录成功返回 Token 和用户信息。
    """
    _logger.info("【login】登录请求: username=%s", request.username)

    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        _logger.warning("【login】登录失败: 用户名或密码错误 username=%s", request.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        _logger.warning("【login】登录失败: 账号已被禁用 username=%s, user_id=%s", request.username, user.id)
        raise HTTPException(status_code=403, detail="账号已被禁用")

    access_token = create_access_token(user.id, user.role.value)
    refresh_token = create_refresh_token(user.id)

    refresh_expires_at = get_token_expiry(refresh_token)
    user.refresh_token = refresh_token
    user.refresh_token_expires_at = refresh_expires_at
    user.last_login_at = datetime.utcnow()

    await db.commit()

    _logger.info("【login】用户登录成功: username=%s, user_id=%s, role=%s", request.username, user.id, user.role.value)

    return success_response(
        data=LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=900,
            user=UserResponse.model_validate(user),
        )
    )


@auth_router.post("/refresh")
async def refresh_token(
    request: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """刷新访问令牌接口。

    Args:
        request: Token 刷新请求参数。
        db: 数据库会话。

    Returns:
        刷新成功返回新的 Token。
    """
    payload = decode_token(request.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的 Refresh Token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    if user.refresh_token != request.refresh_token:
        raise HTTPException(status_code=401, detail="Refresh Token 无效")

    if user.refresh_token_expires_at and user.refresh_token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh Token 已过期")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    new_access_token = create_access_token(user.id, user.role.value)
    new_refresh_token = create_refresh_token(user.id)
    new_refresh_expires_at = get_token_expiry(new_refresh_token)

    user.refresh_token = new_refresh_token
    user.refresh_token_expires_at = new_refresh_expires_at
    user.last_login_at = datetime.utcnow()

    await db.commit()

    _logger.info("【refresh_token】Token 刷新成功: user_id=%s", user.id)

    return success_response(
        data=TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=900,
        )
    )


@auth_router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息接口。

    Args:
        current_user: 当前认证用户。
        db: 数据库会话。

    Returns:
        当前用户信息。
    """
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return success_response(data=UserResponse.model_validate(user))


@auth_router.post("/logout")
async def logout(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户登出接口。

    Args:
        current_user: 当前认证用户。
        db: 数据库会话。

    Returns:
        登出成功消息。
    """
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()

    if user:
        user.refresh_token = None
        user.refresh_token_expires_at = None
        await db.commit()

    _logger.info("【logout】用户登出: user_id=%s", current_user["user_id"])

    return success_response(message="登出成功")


user_router = APIRouter(prefix="/users", tags=["users"])


@user_router.get("/", response_model=UserListResponse)
async def list_users(
    skip: int = 0,
    limit: int = 20,
    role: Optional[str] = None,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表接口（仅管理员可访问）。

    Args:
        skip: 跳过记录数。
        limit: 返回记录数。
        role: 按角色过滤。
        db: 数据库会话。

    Returns:
        用户列表。
    """
    query = select(User)
    if role:
        query = query.where(User.role == UserRole(role))

    count_query = select(User)
    if role:
        count_query = count_query.where(User.role == UserRole(role))

    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    query = query.offset(skip).limit(limit).order_by(User.created_at.desc())
    result = await db.execute(query)
    users = result.scalars().all()

    return success_response(
        data=UserListResponse(
            users=[UserResponse.model_validate(u) for u in users],
            total=total,
        )
    )


@user_router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取指定用户信息接口（仅管理员可访问）。

    Args:
        user_id: 用户 ID。
        db: 数据库会话。

    Returns:
        用户信息。
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return success_response(data=UserResponse.model_validate(user))


@user_router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新用户信息接口（仅管理员可访问）。

    Args:
        user_id: 用户 ID。
        request: 更新请求参数。
        db: 数据库会话。

    Returns:
        更新后的用户信息。
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if request.email:
        existing_email = await db.execute(select(User).where(User.email == request.email, User.id != user_id))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已被使用")

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    _logger.info("【update_user】用户信息更新: user_id=%s", user_id)

    return success_response(data=UserResponse.model_validate(user))


@user_router.put("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    request: UserRoleUpdateRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新用户角色接口（仅管理员可访问）。

    Args:
        user_id: 用户 ID。
        request: 角色更新请求参数。
        db: 数据库会话。

    Returns:
        更新后的用户信息。
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if request.role not in ["admin", "lawyer", "client"]:
        raise HTTPException(status_code=400, detail="无效的角色")

    user.role = UserRole(request.role)
    await db.commit()
    await db.refresh(user)

    _logger.info("【update_user_role】用户角色更新: user_id=%s, new_role=%s", user_id, request.role)

    return success_response(data=UserResponse.model_validate(user))


@user_router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户接口（仅管理员可访问）。

    Args:
        user_id: 用户 ID。
        db: 数据库会话。

    Returns:
        删除成功消息。
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.delete(user)
    await db.commit()

    _logger.info("【delete_user】用户删除: user_id=%s", user_id)

    return success_response(message="用户已删除")


lawyer_router = APIRouter(prefix="/lawyers", tags=["lawyers"])


@lawyer_router.get("/", response_model=LawyerListResponse)
async def list_lawyers(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取律师列表接口（仅管理员可访问）。

    Args:
        db: 数据库会话。

    Returns:
        律师列表。
    """
    result = await db.execute(select(User).where(User.role == UserRole.LAWYER).order_by(User.created_at.desc()))
    lawyers = result.scalars().all()

    return success_response(
        data=LawyerListResponse(
            lawyers=[UserResponse.model_validate(l) for l in lawyers],
            total=len(lawyers),
        )
    )


@lawyer_router.post("/", response_model=UserResponse)
async def create_lawyer(
    request: UserRegisterRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建律师账号接口（仅管理员可访问）。

    Args:
        request: 律师注册请求参数。
        db: 数据库会话。

    Returns:
        创建的律师账号信息。
    """
    existing = await db.execute(select(User).where(User.username == request.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    if request.email:
        existing_email = await db.execute(select(User).where(User.email == request.email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已被使用")

    user = User(
        username=request.username,
        password_hash=hash_password(request.password),
        email=request.email,
        phone=request.phone,
        real_name=request.real_name,
        role=UserRole.LAWYER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _logger.info("【create_lawyer】律师账号创建: user_id=%s", user.id)

    return success_response(data=UserResponse.model_validate(user), message="律师账号创建成功")


@lawyer_router.put("/{lawyer_id}", response_model=UserResponse)
async def update_lawyer(
    lawyer_id: str,
    request: UserUpdateRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新律师信息接口（仅管理员可访问）。

    Args:
        lawyer_id: 律师用户 ID。
        request: 更新请求参数。
        db: 数据库会话。

    Returns:
        更新后的律师信息。
    """
    result = await db.execute(select(User).where(User.id == lawyer_id, User.role == UserRole.LAWYER))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="律师不存在")

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    _logger.info("【update_lawyer】律师信息更新: lawyer_id=%s", lawyer_id)

    return success_response(data=UserResponse.model_validate(user))
