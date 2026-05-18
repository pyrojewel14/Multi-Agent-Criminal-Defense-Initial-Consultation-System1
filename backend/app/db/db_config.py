import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.utils.logger import get_logger

_logger = get_logger("DB")

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/chat_history.db")
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """初始化数据库，创建所有表结构。"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """获取数据库会话的依赖函数。

    Yields:
        数据库会话对象。

    Raises:
        Exception: 数据库操作异常时回滚事务。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()

        except Exception:
            await session.rollback()
            raise

        finally:
            await session.close()


async def check_database_connection() -> bool:
    """检查数据库连接。

    Returns:
        连接成功返回 True，失败返回 False。
    """
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        _logger.error("【check_database_connection】数据库连接失败: %s", e)
        return False


async def close_db() -> None:
    """关闭数据库连接池。"""
    await async_engine.dispose()
    _logger.info("【close_db】数据库连接已关闭")
