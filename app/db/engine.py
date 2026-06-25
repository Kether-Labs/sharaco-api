# app/db/engine.py
from sqlmodel import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Engine synchrone (pour Alembic et les scripts CLI)
engine = create_engine(settings.SYNC_DATABASE_URL, echo=True)

# Engine asynchrone (pour FastAPI)
async_engine = create_async_engine(settings.DATABASE_URL, echo=True)

async_session = sessionmaker(
    async_engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def get_db():
    """Dependency pour injecter une session DB dans les endpoints."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()  # ← Commit automatique
            logger.debug("✅ Transaction commitée")
        except Exception as e:
            await session.rollback()  # ← Rollback en cas d'erreur
            logger.error(f"❌ Rollback: {e}")
            raise
        finally:
            await session.close()