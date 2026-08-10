# app/services/billingSettingsService.py
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.billing_settings import BillingSettings
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


class BillingSettingsService:

    @staticmethod
    async def get_or_create(db: AsyncSession, user_id: UUID) -> BillingSettings:
        """Récupère les settings de l'utilisateur, ou crée les valeurs par défaut."""
        result = await db.execute(
            select(BillingSettings).where(BillingSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            settings = BillingSettings(user_id=user_id)
            db.add(settings)
            await db.flush()
            logger.info(f"✅ Settings par défaut créés pour user {user_id}")

        return settings

    @staticmethod
    async def get(db: AsyncSession, user_id: UUID) -> BillingSettings | None:
        result = await db.execute(
            select(BillingSettings).where(BillingSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update(
        db: AsyncSession,
        user_id: UUID,
        *,
        auto_create_invoice: bool | None = None,
        auto_send_invoice: bool | None = None,
        acompte_percent: float | None = None,
        invoice_prefix: str | None = None,
        invoice_number_format: str | None = None,
        default_payment_terms_days: int | None = None,
        default_late_fee_percent: float | None = None,
        legal_mentions: str | None = None,
    ) -> BillingSettings:
        """Met à jour les settings (crée si inexistant)."""
        settings = await BillingSettingsService.get_or_create(db, user_id)

        if auto_create_invoice is not None:
            settings.auto_create_invoice = auto_create_invoice
        if auto_send_invoice is not None:
            settings.auto_send_invoice = auto_send_invoice
        if acompte_percent is not None:
            # Validation : 0 < percent <= 100
            if not (0 <= acompte_percent <= 100):
                raise ValueError("Le pourcentage d'acompte doit être entre 0 et 100")
            settings.acompte_percent = acompte_percent if acompte_percent > 0 else None
        if invoice_prefix is not None:
            settings.invoice_prefix = invoice_prefix
        if invoice_number_format is not None:
            settings.invoice_number_format = invoice_number_format
        if default_payment_terms_days is not None:
            settings.default_payment_terms_days = default_payment_terms_days
        if default_late_fee_percent is not None:
            settings.default_late_fee_percent = default_late_fee_percent
        if legal_mentions is not None:
            settings.legal_mentions = legal_mentions

        db.add(settings)
        await db.flush()
        logger.info(f"✅ Settings mis à jour pour user {user_id}")
        return settings