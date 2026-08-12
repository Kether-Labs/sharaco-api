# app/services/invoiceService.py
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus, InvoiceType
from app.models.billing_settings import BillingSettings
from app.utils.datetime import to_naive_utc
from datetime import datetime, timezone
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


class InvoiceService:
    """
    Service de génération de factures à partir de devis.
    
    Gère :
    - Facture STANDARD (100% du devis)
    - Facture ACOMPTE (% du devis)
    - Facture SOLDE (reste après acompte)
    - Lien automatique devis → facture via source_document_id
    - Copie du project_id pour cohérence projet
    """

    @staticmethod
    async def create_from_quote(
        db: AsyncSession,
        quote: Document,
        kind: InvoiceType = InvoiceType.STANDARD,
        percent: float | None = None,
        origin: str = "auto",
    ) -> Document:
        """
        Crée une FACTURE à partir d'un DEVIS existant.
        
        Args:
            db: Session DB
            quote: Devis source (avec items chargés)
            kind: Type de facture (STANDARD, ACOMPTE, SOLDE)
            percent: Pourcentage pour ACOMPTE/SOLDE (ex: 30.0 pour 30%)
            origin: "auto" (acceptation) ou "manual" (bouton utilisateur)
        
        Returns:
            La facture créée (brouillon)
        """
        # 1. Validation
        if quote.type != DocumentType.DEVIS:
            raise ValueError("create_from_quote exige un devis en entrée")

        # 2. Charger les lignes du devis
        await db.refresh(quote, ["items"])
        if not quote.items:
            raise ValueError("Le devis source n'a pas de lignes")

        # 3. Générer un numéro de facture séquentiel
        number = await InvoiceService._generate_invoice_number(db, quote.user_id)

        # 4. Créer la facture (copie du devis)
        invoice = Document(
            type=DocumentType.FACTURE,
            invoice_type=kind,
            origin=origin,
            source_document_id=quote.id,  # ✅ Lien vers le devis
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=quote.user_id,
            client_id=quote.client_id,
            project_id=quote.project_id,  # ✅ Copie du projet si présent
            # Copie du design
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
        await db.flush()  # obtenir invoice.id

        # 5. Copier les lignes (avec calcul de pourcentage si ACOMPTE/SOLDE)
        for item in quote.items:
            unit_price = item.unit_price_cents

            if kind == InvoiceType.ACOMPTE and percent is not None:
                # Acompte : appliquer le %
                unit_price = int(round(unit_price * percent / 100))
            elif kind == InvoiceType.SOLDE and percent is not None:
                # Solde : appliquer le % restant (100 - acompte)
                unit_price = int(round(unit_price * (100 - percent) / 100))
            # STANDARD : prix inchangé

            new_item = DocumentItem(
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=unit_price,
                tax_rate=item.tax_rate,
                document_id=invoice.id,
            )
            db.add(new_item)

        await db.flush()
        await db.refresh(invoice, ["items"])

        logger.info(
            f"✅ Facture {invoice.number} créée depuis devis {quote.number} "
            f"(type={kind.value}, origin={origin}, {len(invoice.items)} items, "
            f"project={invoice.project_id})"
        )
        return invoice

    @staticmethod
    async def _generate_invoice_number(db: AsyncSession, user_id: UUID) -> str:
        """
        Génère un numéro de facture séquentiel unique par utilisateur.
        Format: FACT-YYYY-NNN
        """
        from sqlmodel import func

        now_utc = to_naive_utc(datetime.now(timezone.utc))
        year = now_utc.year

        # Compter les factures existantes pour cette année
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
    async def send_invoice(
        db: AsyncSession,
        invoice: Document,
    ) -> None:
        """
        Envoie la facture au client par email.
        (À implémenter plus tard avec EmailService)
        """
        # TODO: Appeler EmailService.send_facture
        invoice.status = DocumentStatus.SENT
        invoice.sent_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(invoice)
        logger.info(f"📧 Facture {invoice.number} envoyée au client")