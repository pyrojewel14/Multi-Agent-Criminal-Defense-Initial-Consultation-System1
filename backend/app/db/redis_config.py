import os
import json
from typing import Any, Optional

import redis.asyncio as redis

from app.utils.logger import get_logger

_logger = get_logger("Redis")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "3"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

_pool: Optional[redis.ConnectionPool] = None


def _get_pool() -> redis.ConnectionPool:
    """Return the shared Redis connection pool, creating it on first call."""
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
        _logger.info(
            "Redis connection pool created: %s:%d db=%d", REDIS_HOST, REDIS_PORT, REDIS_DB
        )
    return _pool


async def connect_redis() -> redis.Redis:
    """Return a Redis client backed by the shared connection pool."""
    pool = _get_pool()
    return redis.Redis(connection_pool=pool)


async def redis_available() -> bool:
    """Check if Redis is reachable via a ping command.

    Returns:
        True if the Redis server responds to PING.
    """
    try:
        client = await connect_redis()
        await client.ping()
        return True
    except Exception:
        return False


async def close_redis() -> None:
    """Close the Redis connection pool and release all connections."""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        _logger.info("Redis connection pool closed")


async def init_redis() -> None:
    """Initialize Redis connection pool"""
    pool = _get_pool()
    try:
        client = redis.Redis(connection_pool=pool)
        await client.ping()
        _logger.info("Redis connection initialized successfully")
    except Exception as e:
        _logger.error("Failed to initialize Redis connection: %s", e)
        raise


async def get_redis_cache_str(key: str) -> Optional[str]:
    """Retrieve a string value from Redis by key."""
    try:
        client = await connect_redis()
        return await client.get(key)
    except Exception as e:
        _logger.error("Redis get failed for key %s: %s", key, e)
        return None


async def get_redis_cache_json(key: str) -> Optional[dict]:
    """Retrieve and deserialize a JSON value from Redis by key."""
    try:
        client = await connect_redis()
        data = await client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        _logger.error("Redis JSON get failed for key %s: %s", key, e)
        return None


async def set_redis_cache(key: str, value: Any, expire: int = 3600) -> bool:
    """Store a value in Redis with an expiry time in seconds.

    Args:
        key: Redis key.
        value: Value to store (str, dict, or list — others converted to str).
        expire: TTL in seconds (default 3600).

    Returns:
        True on success, False on failure.
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
        _logger.error("Redis set failed for key %s: %s", key, e)
        return False
