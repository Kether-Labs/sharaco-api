# app/api/v1/cron.py
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db, async_session  # ⚠️ adapte selon ton engine
from app.core.config import settings
from app.services.reminderService import ReminderService
import logging
from app.services.overdueService import OverdueService
router = APIRouter(tags=["cron"])
logger = logging.getLogger(__name__)


@router.post("/check-overdue")
async def trigger_check_overdue(
    x_cron_secret: str = Header(default=None),
):
    """Marque en OVERDUE toutes les factures en retard."""
    secret = getattr(settings, "CRON_SECRET", None) or "dev-cron-secret"
    if x_cron_secret != secret:
        raise HTTPException(status_code=403, detail="Secret cron invalide")
    
    async with async_session() as db:
        summary = await OverdueService.check_overdue_invoices(db)
    
    logger.info(f"🔴 Cron OVERDUE terminé: {summary}")
    return summary

@router.post("/check-due-invoices")
async def trigger_check_due_invoices(
    x_cron_secret: str = Header(default=None),
):
    """
    Déclenche la vérification des factures arrivant à échéance.
    Protégé par un secret pour être appelé par un cron système ou en test.
    """
    secret = getattr(settings, "CRON_SECRET", None) or "dev-cron-secret"
    if x_cron_secret != secret:
        raise HTTPException(status_code=403, detail="Secret cron invalide")

    async with async_session() as db:
        summary = await ReminderService.check_due_invoices(db)

    logger.info(f"⏰ Cron factures terminé: {summary}")
    return summary