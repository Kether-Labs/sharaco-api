# app/services/paymentScheduleService.py
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus, InvoiceType
from app.utils.datetime import to_naive_utc
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PaymentScheduleService:
    
    @staticmethod
    def _calculate_totals(items: list) -> dict:
        """Calcule les totaux du devis."""
        subtotal = 0
        tax = 0
        for item in items:
            line_sub = item.quantity * item.unit_price_cents
            line_tax = int(line_sub * item.tax_rate / 100)
            subtotal += line_sub
            tax += line_tax
        return {
            "subtotal": subtotal,
            "tax": tax,
            "total": subtotal + tax,
        }

    @staticmethod
    async def set_schedule(
        db: AsyncSession,
        document: Document,
        milestones: list[dict],
    ) -> list[PaymentSchedule]:
        """
        Définit/remplace l'échéancier du devis.
        
        milestones = [
            {"sequence": 1, "title": "Acompte signature", "percent": 30, "trigger_date": None},
            {"sequence": 2, "title": "Mi-parcours", "percent": 40, "trigger_date": None},
            {"sequence": 3, "title": "Livraison", "percent": 30, "trigger_date": None},
        ]
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
        totals = PaymentScheduleService._calculate_totals(document.items)
        
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
            amount = int(round(totals["total"] * ms["percent"] / 100))
            schedule = PaymentSchedule(
                document_id=document.id,
                sequence=ms.get("sequence", len(created) + 1),
                title=ms["title"],
                percent=ms["percent"],
                amount_cents=amount,
                description=ms.get("description"),
                trigger_date=to_naive_utc(ms.get("trigger_date")) if ms.get("trigger_date") else None,
            )
            db.add(schedule)
            created.append(schedule)

        await db.flush()
        for s in created:
            await db.refresh(s)

        logger.info(f"✅ Échéancier créé pour devis {document.number} : {len(created)} échéances")
        return created

    @staticmethod
    async def get_by_document(db: AsyncSession, document_id: UUID) -> list[PaymentSchedule]:
        stmt = (
            select(PaymentSchedule)
            .options(selectinload(PaymentSchedule.invoice))
            .where(PaymentSchedule.document_id == document_id)
            .order_by(PaymentSchedule.sequence.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def invoice_milestone(
        db: AsyncSession,
        milestone: PaymentSchedule,
        document: Document,
        origin: str = "manual",
    ) -> Document:
        """Génère une facture pour une échéance donnée."""
        from app.services.documentService import DocumentService

        if milestone.status != MilestoneStatus.PENDING:
            raise ValueError(f"Cette échéance est déjà {milestone.status.value}")

        # Déterminer le type de facture
        # Si c'est la dernière échéance → SOLDE, sinon → ACOMPTE
        all_milestones = await PaymentScheduleService.get_by_document(db, document.id)
        is_last = milestone.sequence == max(m.sequence for m in all_milestones)
        
        kind = InvoiceType.SOLDE if is_last and len(all_milestones) > 1 else InvoiceType.ACOMPTE

        # Créer la facture avec le montant de l'échéance
        invoice = await DocumentService.create_from_quote(
            db=db,
            quote=document,
            kind=kind,
            percent=milestone.percent,
            origin=origin,
        )

        # Lier la facture à l'échéance
        milestone.invoice_id = invoice.id
        milestone.status = MilestoneStatus.INVOICED
        milestone.invoiced_at = to_naive_utc(datetime.now(timezone.utc))
        
        db.add(milestone)
        await db.flush()

        logger.info(
            f"✅ Facture {invoice.number} générée pour échéance "
            f"'{milestone.title}' ({milestone.percent}%)"
        )
        return invoice

    @staticmethod
    async def mark_as_paid(
        db: AsyncSession,
        milestone: PaymentSchedule,
    ) -> PaymentSchedule:
        """Marque une échéance comme payée."""
        if milestone.status != MilestoneStatus.INVOICED:
            raise ValueError("Seules les échéances facturées peuvent être marquées payées")
        
        milestone.status = MilestoneStatus.PAID
        milestone.paid_at = to_naive_utc(datetime.now(timezone.utc))
        
        # Marquer aussi la facture liée comme payée
        if milestone.invoice_id:
            invoice_stmt = select(Document).where(Document.id == milestone.invoice_id)
            result = await db.execute(invoice_stmt)
            invoice = result.scalar_one_or_none()
            if invoice:
                invoice.status = DocumentStatus.PAID
                db.add(invoice)
        
        db.add(milestone)
        await db.flush()
        return milestone