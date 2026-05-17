import time
from collections import defaultdict
from typing import Dict

from fastapi import Request, HTTPException

from app.utils.logger import get_logger

_logger = get_logger("RateLimit")


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by in-memory data structures.

    Used as a fallback when Redis is unavailable. Each client (by IP) is
    tracked independently with a per-window request counter.

    Attributes:
        limit: Maximum requests allowed within the window.
        window: Time window in seconds.
    """

    def __init__(self, limit: int = 10, window: int = 60):
        self._limit = limit
        self._window = window
        self._clients: Dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_key: str) -> bool:
        """Check whether a client is within the rate limit.

        Args:
            client_key: Identifier for the client (typically IP address).

        Returns:
            True if the request should be allowed.
        """
        now = time.time()
        cutoff = now - self._window
        timestamps = self._clients[client_key]

        timestamps[:] = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= self._limit:
            return False

        timestamps.append(now)
        return True


_limiter: InMemoryRateLimiter = InMemoryRateLimiter()


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP from the request."""
    ip = request.client.host if request.client else None
    if not ip:
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else "unknown"
    return ip


def rate_limit(limit: int = 10, window: int = 60):
    """FastAPI dependency factory for per-endpoint rate limiting.

    Prefers Redis-based rate limiting. Falls back to an in-memory
    sliding-window limiter when Redis is unreachable.

    Args:
        limit: Maximum requests allowed per window.
        window: Time window size in seconds.

    Returns:
        An async FastAPI dependency function.
    """
    async def dependency(request: Request):
        client_ip = _get_client_ip(request)
        key = f"rate_limit:{client_ip}"

        try:
            from app.db.redis_config import connect_redis

            redis = await connect_redis()
            current = await redis.get(key)
            current = int(current) if current else 0

            if current >= limit:
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

            if current == 0:
                await redis.setex(key, window, 1)
            else:
                await redis.incr(key)
        except HTTPException:
            raise
        except Exception:
            _logger.debug("Redis rate-limit unavailable, using in-memory fallback")
            if not _limiter.is_allowed(client_ip):
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    return dependency
