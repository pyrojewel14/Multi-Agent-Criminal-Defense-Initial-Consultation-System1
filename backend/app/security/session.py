import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

_logger = get_logger("Session")


@dataclass
class SessionContext:
    """存储活跃咨询会话的元数据。"""

    session_id: str
    user_type: str
    created_at: float = field(default_factory=time.time)
    ttl: int = 3600

    def is_expired(self) -> bool:
        """判断会话是否已超过 TTL 有效期。

        Returns:
            如果已超时返回 True，否则返回 False。
        """
        return (time.time() - self.created_at) > self.ttl


class SessionStore(ABC):
    """会话持久化后端的抽象接口。

    实现类可使用 Redis、内存字典或其他存储方式。
    """

    @abstractmethod
    async def get(self, session_id: str) -> Optional[SessionContext]:
        """根据 session_id 获取会话，不存在或已过期返回 None。

        Args:
            session_id: 会话标识符。

        Returns:
            会话上下文对象，不存在或已过期返回 None。
        """

    @abstractmethod
    async def set(self, session: SessionContext) -> None:
        """存储会话上下文。

        Args:
            session: 会话上下文对象。
        """

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """从存储中删除会话。

        Args:
            session_id: 会话标识符。
        """

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """判断会话是否存在且未过期。

        Args:
            session_id: 会话标识符。

        Returns:
            如果会话存在且未过期返回 True，否则返回 False。
        """


class InMemorySessionStore(SessionStore):
    """单进程内存会话存储。

    作为 Redis 不可用时的后备方案。会话存储在普通字典中，
    并在访问时惰性清理。
    """

    def __init__(self):
        """初始化内存会话存储。"""
        self._store: dict[str, SessionContext] = {}

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """获取会话，已过期则删除后返回 None。

        Args:
            session_id: 会话标识符。

        Returns:
            会话上下文对象，不存在或已过期返回 None。
        """
        session = self._store.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            await self.delete(session_id)
            return None
        return session

    async def set(self, session: SessionContext) -> None:
        """存储会话上下文。

        Args:
            session: 会话上下文对象。
        """
        self._store[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        """删除会话。

        Args:
            session_id: 会话标识符。
        """
        self._store.pop(session_id, None)

    async def exists(self, session_id: str) -> bool:
        """判断会话是否存在。

        Args:
            session_id: 会话标识符。

        Returns:
            如果会话存在且未过期返回 True，否则返回 False。
        """
        session = await self.get(session_id)
        return session is not None


class RedisSessionStore(SessionStore):
    """Redis 会话存储，支持自动 TTL 过期。

    写入策略：
        每次 set() 调用都会使用配置的 TTL 执行 SETEX，
        会话在过期后会被 Redis 自动清除。

    过期策略：
        依赖 Redis 原生 TTL 和惰性删除，无需额外清理。

    一致性：
        单实例部署默认具有读写一致性。
        分布式部署应考虑 Redis Sentinel/Cluster 配置（MVP 范围外）。

    后备方案：
        当 Redis 不可达时，get_session_store() 自动切换到 InMemorySessionStore。
    """

    KEY_PREFIX = "session"

    def __init__(self, ttl: int = 3600):
        """初始化 Redis 会话存储。

        Args:
            ttl: 会话有效期，单位秒。
        """
        self._ttl = ttl

    async def _get_redis(self):
        """获取 Redis 连接。

        Returns:
            Redis 客户端实例。
        """
        from app.db.redis_config import connect_redis

        return await connect_redis()

    def _key(self, session_id: str) -> str:
        """生成 Redis 键。

        Args:
            session_id: 会话标识符。

        Returns:
            格式化后的 Redis 键。
        """
        return f"{self.KEY_PREFIX}:{session_id}"

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """从 Redis 获取会话。

        Args:
            session_id: 会话标识符。

        Returns:
            会话上下文对象，不存在或错误时返回 None。
        """
        try:
            r = await self._get_redis()
            data = await r.get(self._key(session_id))
            if data is None:
                return None
            import json

            raw = json.loads(data)
            return SessionContext(
                session_id=raw["session_id"],
                user_type=raw["user_type"],
                created_at=raw["created_at"],
                ttl=self._ttl,
            )
        except Exception:
            _logger.warning("Redis 获取会话失败: session_id=%s", session_id)
            return None

    async def set(self, session: SessionContext) -> None:
        """将会话存储到 Redis。

        Args:
            session: 会话上下文对象。
        """
        import json

        try:
            r = await self._get_redis()
            payload = json.dumps(
                {
                    "session_id": session.session_id,
                    "user_type": session.user_type,
                    "created_at": session.created_at,
                },
                ensure_ascii=False,
            )
            await r.setex(self._key(session.session_id), self._ttl, payload)
        except Exception:
            _logger.warning("Redis 存储会话失败: session_id=%s", session.session_id)

    async def delete(self, session_id: str) -> None:
        """从 Redis 删除会话。

        Args:
            session_id: 会话标识符。
        """
        try:
            r = await self._get_redis()
            await r.delete(self._key(session_id))
        except Exception:
            _logger.warning("Redis 删除会话失败: session_id=%s", session_id)

    async def exists(self, session_id: str) -> bool:
        """判断会话是否存在。

        Args:
            session_id: 会话标识符。

        Returns:
            如果会话存在且未过期返回 True，否则返回 False。
        """
        session = await self.get(session_id)
        return session is not None


_session_store: Optional[SessionStore] = None


async def get_session_store() -> SessionStore:
    """返回当前活跃的会话存储，优先使用 Redis。

    首次调用时探测 Redis 可用性。如果 Redis 可达，
    返回 RedisSessionStore；否则回退到 InMemorySessionStore 并记录警告。

    Returns:
        会话存储实例。
    """
    global _session_store

    if _session_store is not None:
        return _session_store

    try:
        from app.db.redis_config import redis_available

        if await redis_available():
            ttl = int(os.getenv("SESSION_TTL", "3600"))
            _session_store = RedisSessionStore(ttl=ttl)
            _logger.info("会话存储: Redis (ttl=%ds)", ttl)
    except Exception:
        _logger.warning("Redis 探测失败，回退到内存存储")

    if _session_store is None:
        _session_store = InMemorySessionStore()
        _logger.info("会话存储: 内存存储（后备）")

    return _session_store


async def generate_session_id(user_type: str) -> str:
    """创建新会话，持久化并返回 session_id。

    Args:
        user_type: 用户类型，取值为 suspect、victim 或 family。

    Returns:
        新的 UUID4 会话标识符。
    """
    session_id = uuid.uuid4().hex
    store = await get_session_store()
    await store.set(SessionContext(session_id=session_id, user_type=user_type))
    _logger.info("会话已创建: %s (user_type=%s)", session_id, user_type)
    return session_id


async def validate_session(session_id: str) -> bool:
    """检查 session_id 是否对应有效且未过期的会话。

    Args:
        session_id: 待验证的会话标识符。

    Returns:
        如果会话存在且未过期返回 True，否则返回 False。
    """
    store = await get_session_store()
    return await store.exists(session_id)


async def get_session_user_type(session_id: str) -> Optional[str]:
    """返回会话关联的用户类型，无效返回 None。

    Args:
        session_id: 会话标识符。

    Returns:
        suspect、victim 或 family 之一，无效返回 None。
    """
    store = await get_session_store()
    session = await store.get(session_id)
    return session.user_type if session else None
