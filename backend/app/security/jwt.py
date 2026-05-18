from datetime import datetime, timedelta
from typing import Optional

import jwt
from passlib.hash import bcrypt

from app.security.config import get_jwt_config
from app.utils.logger import get_logger

_logger = get_logger("JWT")


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.verify(plain_password, hashed_password)


def create_access_token(user_id: str, role: str) -> str:
    config = get_jwt_config()
    expire = datetime.utcnow() + timedelta(minutes=config.get_access_token_expire_minutes())
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, config.get_secret_key(), algorithm=config.get_algorithm())


def create_refresh_token(user_id: str) -> str:
    config = get_jwt_config()
    expire = datetime.utcnow() + timedelta(days=config.get_refresh_token_expire_days())
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, config.get_secret_key(), algorithm=config.get_algorithm())


def decode_token(token: str) -> Optional[dict]:
    config = get_jwt_config()
    try:
        payload = jwt.decode(
            token, 
            config.get_secret_key(), 
            algorithms=[config.get_algorithm()]
        )
        return payload
    except jwt.ExpiredSignatureError:
        _logger.warning("Token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        _logger.warning("无效的 Token: %s", str(e))
        return None


def get_token_expiry(token: str) -> Optional[datetime]:
    config = get_jwt_config()
    try:
        payload = jwt.decode(
            token, 
            config.get_secret_key(), 
            algorithms=[config.get_algorithm()], 
            options={"verify_exp": False}
        )
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp)
        return None
    except Exception:
        return None
