import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


engine = create_async_engine(_database_url(), pool_pre_ping=True)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)
