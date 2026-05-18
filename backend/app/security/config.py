import os
import secrets
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.logger import get_logger

_logger = get_logger("JWTConfig")


class JWTConfigError(Exception):
    """JWT配置异常"""
    pass


class JWTConfig(BaseSettings):
    """JWT配置类，使用pydantic-settings管理配置"""
    
    model_config = SettingsConfigDict(
        env_prefix="JWT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    secret_key: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        description="JWT签名密钥"
    )
    
    algorithm: str = Field(
        default="HS256",
        description="JWT签名算法"
    )
    
    access_token_expire_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description="访问令牌有效期（分钟）"
    )
    
    refresh_token_expire_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="刷新令牌有效期（天）"
    )

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "CHANGE_ME_IN_PRODUCTION":
            _logger.warning(
                "⚠️  SECURITY WARNING: Using default JWT secret key in production is DANGEROUS! "
                "Please set the JWT_SECRET_KEY environment variable with a secure random string. "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        elif len(v) < 32:
            _logger.warning(
                "⚠️  SECURITY WARNING: JWT secret key is too short (< 32 characters). "
                "This is insecure. Please use a longer key (at least 32 characters)."
            )
        return v

    def get_secret_key(self) -> str:
        """获取JWT密钥"""
        return self.secret_key

    def get_algorithm(self) -> str:
        """获取JWT算法"""
        return self.algorithm

    def get_access_token_expire_minutes(self) -> int:
        """获取访问令牌过期时间（分钟）"""
        return self.access_token_expire_minutes

    def get_refresh_token_expire_days(self) -> int:
        """获取刷新令牌过期时间（天）"""
        return self.refresh_token_expire_days


jwt_config: Optional[JWTConfig] = None


def get_jwt_config() -> JWTConfig:
    """获取JWT配置的全局单例
    
    Returns:
        JWTConfig: JWT配置实例
        
    Raises:
        JWTConfigError: 配置加载失败时抛出
    """
    global jwt_config
    
    if jwt_config is None:
        try:
            jwt_config = JWTConfig()
            _logger.info("JWT configuration loaded successfully")
        except Exception as e:
            _logger.error(f"Failed to load JWT configuration: {e}")
            raise JWTConfigError(f"Failed to load JWT configuration: {e}") from e
    
    return jwt_config


def reload_jwt_config() -> JWTConfig:
    """重新加载JWT配置
    
    Returns:
        JWTConfig: 重新加载的配置实例
    """
    global jwt_config
    jwt_config = JWTConfig()
    _logger.info("JWT configuration reloaded")
    return jwt_config
