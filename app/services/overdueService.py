"""
Service de détection automatique des factures en retard.

Logique :
- Scanne toutes les factures SENT/VIEWED
- Si due_date < today → statut passe à OVERDUE
- Idempotent : ne re-marque pas une facture déjà OVERDUE
"""
import logging
from datetime import datetime, timezone
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentType, DocumentStatus
from app.utils.datetime import to_naive_utc

logger = logging.getLogger(__name__)


class OverdueService:
    
    @staticmethod
    async def check_overdue_invoices(db: AsyncSession) -> dict:
        """
        Marque en OVERDUE toutes les factures non payées 
        dont la date d'échéance est dépassée.
        
        Returns:
            {
                "checked": int,      # total factures vérifiées
                "marked": int,       # factures passées en OVERDUE
                "already_paid": int, # déjà payées (ignorées)
                "invoices": [...]    # détails
            }
        """
        now = to_naive_utc(datetime.now(timezone.utc))
        today = now.date()
        today_start = datetime.combine(today, datetime.min.time())
        
        # 1. Récupérer toutes les factures non payées avec due_date
        stmt = (
            select(Document)
            .where(
                Document.type == DocumentType.FACTURE,
                Document.status.in_([
                    DocumentStatus.SENT,
                    DocumentStatus.VIEWED,
                ]),
                Document.due_date != None,
                Document.due_date < today_start,  # ← due_date dans le passé
            )
        )
        result = await db.execute(stmt)
        overdue_invoices = list(result.scalars().all())
        
        marked_count = 0
        details = []
        
        for invoice in overdue_invoices:
            days_late = (today - invoice.due_date.date()).days
            
            invoice.status = DocumentStatus.OVERDUE
            db.add(invoice)
            
            marked_count += 1
            details.append({
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.number,
                "days_late": days_late,
                "due_date": invoice.due_date.isoformat(),
            })
            
            logger.info(
                f"🔴 Facture {invoice.number} marquée OVERDUE "
                f"({days_late} jours de retard)"
            )
        
        await db.commit()
        
        return {
            "checked": len(overdue_invoices),
            "marked": marked_count,
            "invoices": details,
        }
    
    @staticmethod
    async def get_overdue_stats(db: AsyncSession, user_id) -> dict:
        """
        Stats rapides pour le dashboard :
        - Nombre de factures en retard
        - Montant total en retard
        - Facture la plus ancienne en retard
        """
        from sqlalchemy import func
        from sqlalchemy.orm import selectinload
        
        now = to_naive_utc(datetime.now(timezone.utc))
        today = now.date()
        today_start = datetime.combine(today, datetime.min.time())
        
        # Factures OVERDUE avec items pour calcul du total
        stmt = (
            select(Document)
            .options(selectinload(Document.items))
            .where(
                Document.user_id == user_id,
                Document.type == DocumentType.FACTURE,
                Document.status == DocumentStatus.OVERDUE,
            )
            .order_by(Document.due_date.asc())  # Plus anciennes en premier
        )
        result = await db.execute(stmt)
        overdue_invoices = list(result.scalars().all())
        
        total_amount = 0
        oldest_days_late = 0
        
        for invoice in overdue_invoices:
            # Calcul du montant TTC
            subtotal = sum(i.quantity * i.unit_price_cents for i in invoice.items)
            tax = sum(int(i.quantity * i.unit_price_cents * i.tax_rate / 100) for i in invoice.items)
            total_amount += subtotal + tax
            
            # Jours de retard de la plus ancienne
            if invoice.due_date:
                days_late = (today - invoice.due_date.date()).days
                oldest_days_late = max(oldest_days_late, days_late)
        
        return {
            "count": len(overdue_invoices),
            "total_amount_cents": total_amount,
            "oldest_days_late": oldest_days_late,
        }