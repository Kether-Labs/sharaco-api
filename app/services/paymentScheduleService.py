# app/services/paymentScheduleService.py

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus
from app.models.document import Document, DocumentType, DocumentStatus
from app.services.documentService import DocumentService  # ✅ IMPORT
from app.utils.datetime import to_naive_utc
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class PaymentScheduleService:
    
    @staticmethod
    async def set_schedule(
        db: AsyncSession,
        document: Document,
        milestones: list[dict],
    ) -> list[PaymentSchedule]:
        """
        Définit/remplace l'échéancier du devis.
        """
        if document.type != DocumentType.DEVIS:
            raise ValueError("L'échéancier ne peut être défini que sur un devis")
        
        if document.status != DocumentStatus.DRAFT:
            raise ValueError("L'échéancier ne peut être modifié que sur un brouillon")

        # 1. Validation : le total des pourcentages doit faire 100
        total_percent = sum(m.get("percent", 0) for m in milestones)
        if abs(total_percent - 100) > 0.01:
            raise ValueError(f"Le total des pourcentages doit faire 100% (actuel: {total_percent}%)")

        # 2. Charger les items pour calculer les montants
        await db.refresh(document, ["items"])
        
        # ✅ CORRECTION : Utiliser DocumentService.calculate_totals (fiable)
        totals = DocumentService.calculate_totals(document.items)
        grand_total_cents = totals["grand_total_cents"]  # ← Clé correcte
        
        logger.info(f"💰 Total TTC calculé pour échéancier: {grand_total_cents} centimes")
        
        # 3. Supprimer les anciennes échéances (non facturées)
        old_stmt = select(PaymentSchedule).where(PaymentSchedule.document_id == document.id)
        old_result = await db.execute(old_stmt)
        old_milestones = old_result.scalars().all()
        
        for old in old_milestones:
            if old.status == MilestoneStatus.PENDING:
                await db.delete(old)
            else:
                raise ValueError(
                    f"Impossible de modifier l'échéancier : l'échéance '{old.title}' a déjà été facturée"
                )
        
        # 4. Créer les nouvelles échéances
        created = []
        for ms in milestones:
            percent = ms.get("percent", 0)
            
            # ✅ CORRECTION : Utiliser grand_total_cents (pas "total")
            amount = int(round(grand_total_cents * percent / 100))
            
            
            print("---------------------------------------------------------------")

            print(f"DEBUG: Creating milestone '{ms['title']}' with amount {amount} cents and percent {percent}%")
            
            schedule = PaymentSchedule(
                document_id=document.id,
                sequence=ms.get("sequence", len(created) + 1),
                title=ms["title"],
                percent=percent,
                amount_cents=amount,
                description=ms.get("description"),
                trigger_date=to_naive_utc(ms.get("trigger_date")) if ms.get("trigger_date") else None,
            )
            db.add(schedule)
            created.append(schedule)

        await db.flush()
        for s in created:
            await db.refresh(s)

        logger.info(
            f"✅ Échéancier créé pour devis {document.number} : "
            f"{len(created)} échéances (total {grand_total_cents} cents)"
        )
        return created

    # ✅ AJOUTÉ : Méthode utilitaire pour récupérer les milestones d'un document
    @staticmethod
    async def get_by_document(db: AsyncSession, document_id) -> list[PaymentSchedule]:
        """Récupère toutes les milestones d'un document, triées par séquence."""
        stmt = (
            select(PaymentSchedule)
            .where(PaymentSchedule.document_id == document_id)
            .order_by(PaymentSchedule.sequence.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ✅ AJOUTÉ : Méthode pour facturer une milestone
    @staticmethod
    async def invoice_milestone(
        db: AsyncSession,
        milestone: PaymentSchedule,
        quote: Document,
        origin: str = "auto",
    ) -> Document:
        """
        Crée une facture pour une milestone spécifique.
        Délègue à InvoiceService pour éviter la duplication.
        """
        from app.services.invoiceService import InvoiceService
        return await InvoiceService.create_from_milestone(
            db=db,
            quote=quote,
            milestone=milestone,
            origin=origin,
        )