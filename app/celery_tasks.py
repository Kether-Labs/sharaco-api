import asyncio
import logging
from datetime import datetime, timezone, timedelta
from app.celery_config import celery_app
from sqlmodel import select
from app.models.document import Document, DocumentStatus
from app.models.reminder import ReminderConfig, ReminderLog, ReminderStatus
from app.models.user import User
from app.models.client import Client
from app.db.engine import async_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


async def _check_and_send_reminders():
    """
    Tâche principale :
    1. Trouve les documents SENT qui nécessitent une relance
    2. Vérifie la config de chaque utilisateur
    3. Envoie les relances si nécessaire
    """
    async_session = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # Trouver tous les documents envoyés (SENT ou VIEWED) qui ne sont pas payés
        statement = select(Document).where(
            Document.status.in_([DocumentStatus.SENT, DocumentStatus.VIEWED]),
        )
        result = await db.execute(statement)
        documents = list(result.scalars().all())

        logger.info(f"Vérification de {len(documents)} document(s) en attente...")

        for doc in documents:
            if not doc.sent_at:
                continue

            days_since_sent = (now - doc.sent_at.replace(tzinfo=timezone.utc)).days

            # Récupérer la config de l'utilisateur
            config_stmt = select(ReminderConfig).where(ReminderConfig.user_id == doc.user_id)
            config_result = await db.execute(config_stmt)
            config = config_result.scalar_one_or_none()

            if not config or not config.is_active:
                continue

            # Vérifier stop_on_payment
            if config.stop_on_payment and doc.status == DocumentStatus.PAID:
                continue

            # Vérifier stop_on_view
            if config.stop_on_view and doc.viewed_at is not None:
                continue

            # Vérifier chaque niveau de relance
            for level in [1, 2, 3]:
                enabled = getattr(config, f"reminder_{level}_enabled", False)
                delay_days = getattr(config, f"reminder_{level}_days", 0)

                if not enabled or delay_days == 0:
                    continue

                # Est-ce que le délai est atteint ?
                if days_since_sent < delay_days:
                    continue

                # Est-ce qu'on a déjà envoyé cette relance ?
                log_stmt = select(ReminderLog).where(
                    ReminderLog.document_id == doc.id,
                    ReminderLog.reminder_level == level,
                    ReminderLog.status == ReminderStatus.SENT,
                )
                log_result = await db.execute(log_stmt)
                existing_log = log_result.scalar_one_or_none()

                if existing_log:
                    continue  # Déjà envoyé

                # Récupérer le user et le client
                user_stmt = select(User).where(User.id == doc.user_id)
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()

                client_stmt = select(Client).where(Client.id == doc.client_id)
                client_result = await db.execute(client_stmt)
                client = client_result.scalar_one_or_none()

                if not user or not client or not client.email:
                    continue

                # Envoyer la relance
                try:
                    from app.services.reminderService import reminder_service
                    await reminder_service.send_reminder(
                        db=db,
                        document=doc,
                        user=user,
                        client=client,
                        reminder_level=level,
                    )
                    logger.info(f"Relance niveau {level} envoyée pour {doc.number}")
                except Exception as e:
                    logger.error(f"Erreur relance {doc.number} niveau {level}: {str(e)}")


@celery_app.task(name="app.celery_tasks.check_and_send_reminders")
def check_and_send_reminders():
    """Wrapper sync pour la tâche async Celery."""
    asyncio.run(_check_and_send_reminders())