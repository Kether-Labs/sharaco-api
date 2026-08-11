# app/services/documentService.py
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus, InvoiceType
from app.models.document_template import DocumentTemplate
from app.models.reminder import ReminderLog
from app.models.billing_settings import BillingSettings
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone
from app.services.templateService import TemplateService
from app.services.billingSettingsService import BillingSettingsService
from uuid import uuid4
from app.models.client import Client
from app.models.user import User
from app.services.pdfRenderer import pdf_renderer
import logging
from app.utils.datetime import to_naive_utc

logger = logging.getLogger(__name__)


class DocumentService:

    # ============================================================
    #  ✅ NOUVELLE MÉTHODE : créer une facture à partir d'un devis
    # ============================================================
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

        - kind : STANDARD (100%), ACOMPTE (%), SOLDE (reste après acompte)
        - percent : utilisé uniquement pour ACOMPTE (ex: 30.0 = 30%)
        - origin : "manual" (bouton utilisateur) ou "auto" (acceptation client)
        """
        if quote.type != DocumentType.DEVIS:
            raise ValueError("create_from_quote exige un devis en entrée")

        # 1. Charger les lignes du devis
        await db.refresh(quote, ["items"])
        if not quote.items:
            raise ValueError("Le devis source n'a pas de lignes")

        # 2. Générer un numéro de facture séquentiel
        number = await DocumentService._generate_number(db, DocumentType.FACTURE, quote.user_id)

        # 3. Créer le document facture
        invoice = Document(
            type=DocumentType.FACTURE,
            invoice_type=kind,
            origin=origin,
            source_document_id=quote.id,
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=quote.user_id,
            client_id=quote.client_id,
            layout_style=quote.layout_style,
            template_id=quote.template_id,
            project_id=quote.project_id,
            notes=quote.notes,
            primary_color=quote.primary_color,
            secondary_color=quote.secondary_color,
            accent_color=quote.accent_color,
            background_color=quote.background_color,
            text_color=quote.text_color,
            font_family=quote.font_family,
            show_bank_details=quote.show_bank_details,
            show_tax_id=quote.show_tax_id,
            created_at=to_naive_utc(datetime.now(timezone.utc)),
        )
        db.add(invoice)
        await db.flush()  # obtenir invoice.id

        # 4. Copier les lignes (avec calcul de pourcentage si ACOMPTE)
        for item in quote.items:
            # Prix de base
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
            f"(type={kind.value}, origin={origin}, {len(invoice.items)} items)"
        )
        return invoice

    # ============================================================
    #  ✅ NOUVEAU : handler d'acceptation (appelé quand le client signe)
    # ============================================================
    @staticmethod
    async def handle_quote_acceptance(db: AsyncSession, quote: Document) -> dict:
    
        from app.services.billingSettingsService import BillingSettingsService
        from app.services.paymentScheduleService import PaymentScheduleService

        quote.status = DocumentStatus.ACCEPTED
        quote.accepted_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(quote)

        settings = await BillingSettingsService.get_or_create(db, quote.user_id)
        first_invoice = None

        # Charger l'échéancier
        milestones = await PaymentScheduleService.get_by_document(db, quote.id)

        if settings.auto_create_invoice:
            if milestones:
                # ✅ CAS ÉCHÉANCIER : facturer uniquement la 1ère échéance
                first = next((m for m in milestones if m.sequence == 1), None)
                if first:
                    first_invoice = await PaymentScheduleService.invoice_milestone(
                        db, first, quote, origin="auto"
                    )
            else:
                # ✅ CAS CLASSIQUE : facture standard brouillon
                first_invoice = await DocumentService.create_from_quote(
                    db=db, quote=quote, kind=InvoiceType.STANDARD, origin="auto"
                )

            if settings.auto_send_invoice and first_invoice:
                first_invoice.status = DocumentStatus.SENT
                first_invoice.sent_at = to_naive_utc(datetime.now(timezone.utc))
                db.add(first_invoice)

        await db.flush()
        await db.refresh(quote)

        return {
            "quote": quote,
            "invoice": first_invoice,
            "has_schedule": bool(milestones),
            "auto_sent": bool(first_invoice and settings.auto_send_invoice),
        }
    def _parse_trigger_date(value) -> datetime | None:
        """Parse une date ISO (string) en datetime naive UTC."""
        if not value:
            return None
        if isinstance(value, datetime):
            return to_naive_utc(value)
        if isinstance(value, str):
            try:
                # Gère "2026-08-15" ET "2026-08-15T00:00:00" ET "2026-08-15T12:00:00Z"
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                return to_naive_utc(dt)
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Impossible de parser la date '{value}': {e}")
                return None
        return None
    # ============================================================
    #  ✅ APERÇU EN TEMPS RÉEL (pour le preview du frontend)
    # ============================================================
    @staticmethod
    async def render_preview(
        db: AsyncSession,
        user: User,
        type: DocumentType = DocumentType.DEVIS,
        client_name: str = "Client Exemple",
        client_email: str = "",
        client_address: str = "",
        client_phone: str = "",
        items: list[dict] = None,
        template_id: Optional[UUID] = None,
        layout_style: str = "classic",
        primary_color: str = "#2563EB",
        secondary_color: str = "#1E40AF",
        accent_color: str = "#DBEAFE",
        text_color: str = "#1F2937",
        background_color: str = "#FFFFFF",
        font_family: str = "Inter",
        header_text: Optional[str] = None,
        footer_text: Optional[str] = None,
        show_bank_details: bool = True,
        show_tax_id: bool = True,
        reference: Optional[str] = None,
        payment_schedule: Optional[list[dict]] = None,  # ✅ Échéancier pour le preview
    ) -> str:
        """Génère un aperçu HTML en temps réel (sans sauvegarder en base)."""
        items = items or [{"description": "Exemple", "quantity": 1, "unit_price_cents": 0, "tax_rate": 20}]

        # 1. Template
        if template_id:
            template = await TemplateService.get_by_id(db, template_id, user.id)
            if not template:
                template = DocumentService._build_fallback_template(user.id, layout_style)
        else:
            template = DocumentTemplate(
                id=uuid4(),
                name="Aperçu",
                user_id=user.id,
                layout_style=layout_style,
                primary_color=primary_color,
                secondary_color=secondary_color,
                accent_color=accent_color,
                text_color=text_color,
                background_color=background_color,
                font_family=font_family,
                header_text=header_text,
                footer_text=footer_text,
                show_bank_details=show_bank_details,
                show_tax_id=show_tax_id,
            )

        # 2. Document temporaire (non persisté)
        doc_id = uuid4()
        fake_doc = Document(
            id=doc_id,
            type=type,
            status=DocumentStatus.DRAFT,
            number=reference or ("DEV-2026-001" if type == DocumentType.DEVIS else "FACT-2026-001"),
            created_at=to_naive_utc(datetime.now(timezone.utc)),
            due_date=None,
            user_id=user.id,
            client_id=uuid4(),
        )

        fake_doc.items = [
            DocumentItem(
                id=uuid4(),
                description=item.get("description", ""),
                quantity=item.get("quantity", 1),
                unit_price_cents=item.get("unit_price_cents", 0),
                tax_rate=item.get("tax_rate", 20),
                document_id=doc_id,
            )
            for item in items
        ]

        # 3. ✅ Créer des faux PaymentSchedule pour l'aperçu
        if payment_schedule:
            from app.models.payment_schedule import PaymentSchedule
            
            # Calculer le total TTC pour les montants
            totals = DocumentService.calculate_totals(fake_doc.items)
            
            fake_doc.payment_schedule = [
                PaymentSchedule(
                    id=uuid4(),
                    document_id=doc_id,
                    sequence=ms.get("sequence", idx + 1),
                    title=ms.get("title", f"Échéance {idx + 1}"),
                    percent=ms.get("percent", 0),
                    amount_cents=int(round(totals["grand_total_cents"] * ms.get("percent", 0) / 100)),
                    description=ms.get("description"),
                    trigger_date=DocumentService._parse_trigger_date(ms.get("trigger_date")),
                    status="PENDING",
                )
                for idx, ms in enumerate(payment_schedule)
            ]
        else:
            fake_doc.payment_schedule = []

        # 4. Client temporaire
        fake_client = Client(
            id=uuid4(),
            name=client_name,
            email=client_email,
            address=client_address,
            phone=client_phone,
            user_id=user.id,
        )

        # 5. Rendu HTML
        return pdf_renderer.render_html(
            document=fake_doc,
            template=template,
            user=user,
            client=fake_client,
        )

    # ============================================================
    #  📄 Méthodes existantes (inchangées)
    # ============================================================

    @staticmethod
    async def create_document(
        db: AsyncSession,
        type: DocumentType,
        user_id: UUID,
        client_id: UUID,
        items: list[dict],
        layout_style: str = "classic",
        template_id: Optional[UUID] = None,
        due_date: Optional[datetime] = None,
        notes: Optional[str] = None,
        document_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        invoice_type: Optional[InvoiceType] = None,
        source_document_id: Optional[UUID] = None,
        origin: str = "manual",
    ) -> Document:
        """Crée un document avec layout_style ou template_id."""
        logger.info(f"🔨 create_document appelé avec document_id={document_id}, layout={layout_style}")

        if document_id:
            existing = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            existing_doc = existing.scalar_one_or_none()

            if existing_doc:
                logger.info(f"📄 Document {document_id} existe déjà, mise à jour")
                existing_doc.type = type
                existing_doc.client_id = client_id
                existing_doc.layout_style = layout_style
                existing_doc.template_id = template_id
                existing_doc.due_date = to_naive_utc(due_date)
                existing_doc.notes = notes
                existing_doc.project_id = project_id
                existing_doc.invoice_type = invoice_type
                existing_doc.source_document_id = source_document_id
                existing_doc.origin = origin

                for old_item in list(existing_doc.items):
                    await db.delete(old_item)
                await db.flush()

                for item_data in items:
                    item = DocumentItem(
                        description=item_data["description"],
                        quantity=item_data.get("quantity", 1),
                        unit_price_cents=item_data["unit_price_cents"],
                        tax_rate=item_data.get("tax_rate", 20),
                        document_id=existing_doc.id,
                    )
                    db.add(item)

                await db.flush()
                await db.refresh(existing_doc, ['items'])
                return existing_doc

        if template_id:
            tmpl = await db.execute(
                select(DocumentTemplate).where(
                    DocumentTemplate.id == template_id,
                    DocumentTemplate.user_id == user_id,
                )
            )
            if not tmpl.scalar_one_or_none():
                raise ValueError("Template introuvable")

        number = await DocumentService._generate_number(db, type, user_id)
        now_utc = to_naive_utc(datetime.now(timezone.utc))
        due_date_utc = to_naive_utc(due_date)

        document = Document(
            id=document_id or uuid4(),
            type=type,
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=user_id,
            client_id=client_id,
            layout_style=layout_style,
            template_id=template_id,
            created_at=now_utc,
            due_date=due_date_utc,
            notes=notes,
            project_id=project_id,
            invoice_type=invoice_type,
            source_document_id=source_document_id,
            origin=origin,
        )
        db.add(document)
        await db.flush()

        for item_data in items:
            item = DocumentItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1),
                unit_price_cents=item_data["unit_price_cents"],
                tax_rate=item_data.get("tax_rate", 20),
                document_id=document.id,
            )
            db.add(item)

        await db.flush()
        await db.refresh(document, ['items'])
        return document

    @staticmethod
    async def get_by_id(db: AsyncSession, document_id: UUID, user_id: UUID) -> Document | None:
        statement = (
            select(Document)
            .options(selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.payment_schedule))
            .where(Document.id == document_id, Document.user_id == user_id)
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        user_id: UUID,
        type: Optional[DocumentType] = None,
        status: Optional[DocumentStatus] = None,
        client_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Document]:
        statement = (
            select(Document)
            .options(selectinload(Document.items), selectinload(Document.client),selectinload(Document.payment_schedule))
            .where(Document.user_id == user_id)
        )
        if type:
            statement = statement.where(Document.type == type)
        if status:
            statement = statement.where(Document.status == status)
        if client_id:
            statement = statement.where(Document.client_id == client_id)
        if project_id:
            statement = statement.where(Document.project_id == project_id)

        statement = statement.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    async def update_status(db, document, new_status):
        valid_transitions = {
            DocumentStatus.DRAFT: [DocumentStatus.SENT],
            DocumentStatus.SENT: [DocumentStatus.VIEWED, DocumentStatus.PAID],
            DocumentStatus.VIEWED: [DocumentStatus.PAID],
            DocumentStatus.PAID: [],
        }
        if new_status not in valid_transitions.get(document.status, []):
            raise ValueError(f"Transition invalide : {document.status.value} → {new_status.value}")
        document.status = new_status
        db.add(document)
        await db.flush()
        await db.refresh(document)
        return document

    @staticmethod
    async def update_document(db, document, client_id=None, template_id=None, layout_style=None,
                               due_date=None, items=None, notes=None,
                               primary_color=None, secondary_color=None, accent_color=None,
                               background_color=None, text_color=None, font_family=None,
                               show_bank_details=None, show_tax_id=None):
        if client_id is not None: document.client_id = client_id
        if template_id is not None: document.template_id = template_id
        if layout_style is not None: document.layout_style = layout_style
        if due_date is not None: document.due_date = to_naive_utc(due_date)
        if notes is not None: document.notes = notes
        if primary_color is not None: document.primary_color = primary_color
        if secondary_color is not None: document.secondary_color = secondary_color
        if accent_color is not None: document.accent_color = accent_color
        if background_color is not None: document.background_color = background_color
        if text_color is not None: document.text_color = text_color
        if font_family is not None: document.font_family = font_family
        if show_bank_details is not None: document.show_bank_details = show_bank_details
        if show_tax_id is not None: document.show_tax_id = show_tax_id

        if items is not None:
            for old_item in list(document.items):
                await db.delete(old_item)
            await db.flush()
            document.items = []
            for item_data in items:
                item = DocumentItem(
                    description=item_data["description"],
                    quantity=item_data.get("quantity", 1),
                    unit_price_cents=item_data["unit_price_cents"],
                    tax_rate=item_data.get("tax_rate", 20),
                    document_id=document.id,
                )
                db.add(item)
        await db.commit()
        await db.refresh(document, ['items'])
        return document

    @staticmethod
    async def delete_document(db, document_id, user_id):
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(Document)
            .options(selectinload(Document.items), selectinload(Document.reminder_logs), selectinload(Document.views))
            .where(Document.id == document_id, Document.user_id == user_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError("Document introuvable")
        if document.status != DocumentStatus.DRAFT:
            raise ValueError("Seuls les brouillons peuvent être supprimés")
        await db.delete(document)
        await db.commit()

    @staticmethod
    async def duplicate_as_invoice(db, document):
        if document.type != DocumentType.DEVIS:
            raise ValueError("Seuls les devis peuvent être convertis en facture")
        await db.refresh(document, ['items'])
        items_data = [
            {"description": i.description, "quantity": i.quantity,
             "unit_price_cents": i.unit_price_cents, "tax_rate": i.tax_rate}
            for i in document.items
        ]
        return await DocumentService.create_document(
            db=db, type=DocumentType.FACTURE, user_id=document.user_id,
            client_id=document.client_id, items=items_data,
            layout_style=getattr(document, 'layout_style', 'classic'),
            template_id=document.template_id, due_date=document.due_date,
            notes=document.notes,
            invoice_type=InvoiceType.STANDARD,
            source_document_id=document.id,
            origin="manual",
        )

    @staticmethod
    def calculate_totals(items):
        subtotal_cents = 0
        tax_total_cents = 0
        for item in items:
            line_subtotal = item.quantity * item.unit_price_cents
            line_tax = int(line_subtotal * item.tax_rate / 100)
            subtotal_cents += line_subtotal
            tax_total_cents += line_tax
        return {
            "subtotal_cents": subtotal_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": subtotal_cents + tax_total_cents,
        }

    @staticmethod
    async def _generate_number(db, type, user_id):
        prefix = "DEV" if type == DocumentType.DEVIS else "FACT"
        now_utc = to_naive_utc(datetime.now(timezone.utc))
        year = now_utc.year
        count_stmt = (
            select(func.count(Document.id))
            .where(
                Document.user_id == user_id,
                Document.type == type,
                func.extract('year', Document.created_at) == year,
            )
        )
        result = await db.execute(count_stmt)
        count = result.scalar() or 0
        return f"{prefix}-{year}-{count + 1:03d}"

    @staticmethod
    def _build_fallback_template(user_id: UUID, layout_style: str = "classic") -> DocumentTemplate:
        """Template fallback avec valeurs par défaut."""
        return DocumentTemplate(
            id=uuid4(),
            name="Par défaut",
            user_id=user_id,
            layout_style=layout_style,
            primary_color="#2563EB",
            secondary_color="#1E40AF",
            accent_color="#DBEAFE",
            text_color="#1F2937",
            background_color="#FFFFFF",
            font_family="Inter",
            show_bank_details=True,
            show_tax_id=True,
        )