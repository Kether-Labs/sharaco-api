from sqlmodel import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Engine synchrone (pour Alembic et les scripts CLI)
engine = create_engine(settings.SYNC_DATABASE_URL, echo=True)

# Engine asynchrone (pour FastAPI)
async_engine = create_async_engine(settings.DATABASE_URL, echo=True)

# Générateur de session async pour FastAPI
async def get_db():
    async_session = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
