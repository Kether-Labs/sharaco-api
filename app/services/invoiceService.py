# app/services/invoiceService.py

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus, InvoiceType
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus
from app.utils.datetime import to_naive_utc
from datetime import datetime, timezone
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service de génération de factures à partir de devis/milestones."""

    @staticmethod
    async def create_from_quote(
        db: AsyncSession,
        quote: Document,
        kind: InvoiceType = InvoiceType.STANDARD,
        percent: float | None = None,
        origin: str = "auto",
    ) -> Document:
        """Crée une facture complète (100%) depuis un devis."""
        if quote.type != DocumentType.DEVIS:
            raise ValueError("create_from_quote exige un devis en entrée")

        await db.refresh(quote, ["items"])
        if not quote.items:
            raise ValueError("Le devis source n'a pas de lignes")

        number = await InvoiceService._generate_invoice_number(db, quote.user_id)

        invoice = Document(
            type=DocumentType.FACTURE,
            invoice_type=kind,
            origin=origin,
            source_document_id=quote.id,
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=quote.user_id,
            client_id=quote.client_id,
            project_id=quote.project_id,
            layout_style=quote.layout_style,
            template_id=quote.template_id,
            primary_color=quote.primary_color,
            secondary_color=quote.secondary_color,
            accent_color=quote.accent_color,
            background_color=quote.background_color,
            text_color=quote.text_color,
            font_family=quote.font_family,
            show_bank_details=quote.show_bank_details,
            show_tax_id=quote.show_tax_id,
            notes=quote.notes,
            created_at=to_naive_utc(datetime.now(timezone.utc)),
        )
        db.add(invoice)
        await db.flush()

        for item in quote.items:
            unit_price = item.unit_price_cents
            if kind == InvoiceType.ACOMPTE and percent is not None:
                unit_price = int(round(unit_price * percent / 100))
            elif kind == InvoiceType.SOLDE and percent is not None:
                unit_price = int(round(unit_price * (100 - percent) / 100))

            db.add(DocumentItem(
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=unit_price,
                tax_rate=item.tax_rate,
                document_id=invoice.id,
            ))

        await db.flush()
        await db.refresh(invoice, ["items"])
        logger.info(f"✅ Facture {invoice.number} (type={kind.value}) créée depuis devis {quote.number}")
        return invoice

    @staticmethod
    async def create_from_milestone(
        db: AsyncSession,
        quote: Document,
        milestone: PaymentSchedule,
        origin: str = "auto",
    ) -> Document:
        """
        Crée une facture pour UNE milestone spécifique.
        
        Détermine automatiquement le type :
        - ACOMPTE si ce n'est pas la dernière milestone
        - SOLDE si c'est la dernière milestone
        """
        if quote.type != DocumentType.DEVIS:
            raise ValueError("create_from_milestone exige un devis en entrée")
        
        if milestone.status == MilestoneStatus.INVOICED:
            raise ValueError(f"Cette milestone a déjà été facturée ({milestone.invoice_id})")

        await db.refresh(quote, ["items"])
        if not quote.items:
            raise ValueError("Le devis source n'a pas de lignes")

        # Charger toutes les milestones pour savoir si c'est la dernière
        stmt = (
            select(PaymentSchedule)
            .where(PaymentSchedule.document_id == quote.id)
            .order_by(PaymentSchedule.sequence.asc())
        )
        result = await db.execute(stmt)
        all_milestones = list(result.scalars().all())
        
        is_last = milestone.sequence == max(m.sequence for m in all_milestones)
        kind = InvoiceType.SOLDE if (is_last and len(all_milestones) > 1) else InvoiceType.ACOMPTE

        number = await InvoiceService._generate_invoice_number(db, quote.user_id)

        invoice = Document(
            type=DocumentType.FACTURE,
            invoice_type=kind,
            origin=origin,
            source_document_id=quote.id,
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=quote.user_id,
            client_id=quote.client_id,
            project_id=quote.project_id,
            layout_style=quote.layout_style,
            template_id=quote.template_id,
            primary_color=quote.primary_color,
            secondary_color=quote.secondary_color,
            accent_color=quote.accent_color,
            background_color=quote.background_color,
            text_color=quote.text_color,
            font_family=quote.font_family,
            show_bank_details=quote.show_bank_details,
            show_tax_id=quote.show_tax_id,
            notes=(
                f"{quote.notes or ''}\n\n"
                f"Échéance {milestone.sequence}: {milestone.title} "
                f"({milestone.percent}%)"
            ).strip(),
            created_at=to_naive_utc(datetime.now(timezone.utc)),
        )
        db.add(invoice)
        await db.flush()

        # Copier les items avec le pourcentage appliqué
        for item in quote.items:
            unit_price = int(round(item.unit_price_cents * milestone.percent / 100))
            db.add(DocumentItem(
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=unit_price,
                tax_rate=item.tax_rate,
                document_id=invoice.id,
            ))

        await db.flush()
        await db.refresh(invoice, ["items"])
        
        logger.info(
            f"✅ Facture {invoice.number} ({kind.value}) créée pour milestone "
            f"'{milestone.title}' ({milestone.percent}%) - project={invoice.project_id}"
        )
        return invoice

    @staticmethod
    async def _generate_invoice_number(db: AsyncSession, user_id: UUID) -> str:
        """Génère un numéro de facture séquentiel."""
        from sqlmodel import func
        now_utc = to_naive_utc(datetime.now(timezone.utc))
        year = now_utc.year
        
        count_stmt = (
            select(func.count(Document.id))
            .where(
                Document.user_id == user_id,
                Document.type == DocumentType.FACTURE,
                func.extract('year', Document.created_at) == year,
            )
        )
        result = await db.execute(count_stmt)
        count = result.scalar() or 0
        return f"FACT-{year}-{count + 1:03d}"

    @staticmethod
    async def send_invoice(db: AsyncSession, invoice: Document) -> None:
        """Envoie la facture au client (à implémenter avec EmailService)."""
        invoice.status = DocumentStatus.SENT
        invoice.sent_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(invoice)
        logger.info(f"📧 Facture {invoice.number} envoyée")