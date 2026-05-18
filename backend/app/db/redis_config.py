import json
import os
from typing import Any, Optional

import redis.asyncio as redis

from app.utils.logger import get_logger

_logger = get_logger("DB.Redis")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "3"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

_pool: Optional[redis.ConnectionPool] = None


def _get_pool() -> redis.ConnectionPool:
    """获取共享的 Redis 连接池，首次调用时创建。

    Returns:
        Redis 连接池实例。
    """
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            max_connections=10,
            decode_responses=True,
        )
        _logger.info("【_get_pool】Redis 连接池已创建: %s:%d db=%d", REDIS_HOST, REDIS_PORT, REDIS_DB)
    return _pool


async def connect_redis() -> redis.Redis:
    """返回使用共享连接池的 Redis 客户端。

    Returns:
        Redis 客户端实例。
    """
    pool = _get_pool()
    return redis.Redis(connection_pool=pool)


async def redis_available() -> bool:
    """检查 Redis 是否可通过 ping 命令访问。

    Returns:
        如果 Redis 服务器响应 PING 返回 True，否则返回 False。
    """
    try:
        client = await connect_redis()
        await client.ping()
        return True
    except Exception:
        return False


async def close_redis() -> None:
    """关闭 Redis 连接池并释放所有连接。"""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        _logger.info("【close_redis】Redis 连接池已关闭")


async def init_redis() -> None:
    """初始化 Redis 连接池。

    Raises:
        Exception: Redis 连接初始化失败时抛出。
    """
    pool = _get_pool()
    try:
        client = redis.Redis(connection_pool=pool)
        await client.ping()
        _logger.info("【init_redis】Redis 连接初始化成功")
    except Exception as e:
        _logger.error("【init_redis】Redis 连接初始化失败: %s", e)
        raise


async def get_redis_cache_str(key: str) -> Optional[str]:
    """根据键从 Redis 检索字符串值。

    Args:
        key: Redis 键。

    Returns:
        缓存的字符串值，不存在或错误返回 None。
    """
    try:
        client = await connect_redis()
        return await client.get(key)
    except Exception as e:
        _logger.error("【get_redis_cache_str】Redis 获取失败 key=%s: %s", key, e)
        return None


async def get_redis_cache_json(key: str) -> Optional[dict]:
    """根据键从 Redis 检索并反序列化 JSON 值。

    Args:
        key: Redis 键。

    Returns:
        反序列化后的字典，不存在或错误返回 None。
    """
    try:
        client = await connect_redis()
        data = await client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        _logger.error("【get_redis_cache_json】Redis JSON 获取失败 key=%s: %s", key, e)
        return None


async def set_redis_cache(key: str, value: Any, expire: int = 3600) -> bool:
    """在 Redis 中存储值，设置过期时间（秒）。

    Args:
        key: Redis 键。
        value: 要存储的值（str、dict 或 list — 其他类型转换为 str）。
        expire: TTL 秒数（默认 3600）。

    Returns:
        成功返回 True，失败返回 False。
    """
    try:
        client = await connect_redis()
        if isinstance(value, str):
            await client.set(key, value, ex=expire)
        elif isinstance(value, (dict, list)):
            await client.set(key, json.dumps(value, ensure_ascii=False), ex=expire)
        else:
            await client.set(key, str(value), ex=expire)
        return True
    except Exception as e:
        _logger.error("【set_redis_cache】Redis 存储失败 key=%s: %s", key, e)
        return False
