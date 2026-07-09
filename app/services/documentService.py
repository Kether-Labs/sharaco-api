# app/services/documentService.py
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus
from app.models.document_template import DocumentTemplate
from app.models.reminder import ReminderLog
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone
from app.services.templateService import TemplateService
from uuid import uuid4
from app.models.client import Client
from app.models.user import User
from app.services.pdfRenderer import pdf_renderer
import logging
from app.utils.datetime import to_naive_utc

logger = logging.getLogger(__name__)


class DocumentService:
    
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
    ) -> Document:
        """Crée un document avec layout_style ou template_id."""
        logger.info(f"🔨 create_document appelé avec document_id={document_id}, layout={layout_style}")

        # ✅ Vérifier si le document existe déjà (upsert)
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
                
                # Supprimer les anciens items
                for old_item in list(existing_doc.items):
                    await db.delete(old_item)
                await db.flush()
                
                # Créer les nouveaux items
                for item_data in items:
                    item = DocumentItem(
                        description=item_data["description"],
                        quantity=item_data.get("quantity", 1),
                        unit_price_cents=item_data["unit_price_cents"],
                        tax_rate=item_data.get("tax_rate", 20),
                        document_id=existing_doc.id,
                    )
                    db.add(item)
                
                # ✅ NE PAS faire commit() ici, laisser get_db gérer
                await db.flush()
                
                # Recharger avec les items
                await db.refresh(existing_doc, ['items'])
                logger.info(f"✅ Document {existing_doc.id} mis à jour avec {len(existing_doc.items)} items")
                return existing_doc

        # Si template_id fourni, vérifier qu'il existe
        if template_id:
            tmpl = await db.execute(
                select(DocumentTemplate).where(
                    DocumentTemplate.id == template_id,
                    DocumentTemplate.user_id == user_id,
                )
            )
            if not tmpl.scalar_one_or_none():
                raise ValueError("Template introuvable")

        # Générer le numéro
        number = await DocumentService._generate_number(db, type, user_id)

        # ✅ Convertir les datetimes en UTC naive
        now_utc = to_naive_utc(datetime.now(timezone.utc))
        due_date_utc = to_naive_utc(due_date)

        # Créer le document
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
            project_id=project_id
        )
        db.add(document)
        await db.flush()  # ← flush() pour obtenir l'ID, pas commit()
        logger.info(f"📝 Document {document.id} ajouté à la session")

        # Créer les items
        for item_data in items:
            item = DocumentItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1),
                unit_price_cents=item_data["unit_price_cents"],
                tax_rate=item_data.get("tax_rate", 20),
                document_id=document.id,
            )
            db.add(item)

        # ✅ NE PAS faire commit() ici, laisser get_db gérer
        await db.flush()
        logger.info(f"✅ {len(items)} items ajoutés au document {document.id}")
        
        # Recharger les items
        await db.refresh(document, ['items'])
        logger.info(f"✅ Document {document.id} prêt avec {len(document.items)} items")
        
        return document

    @staticmethod
    async def get_by_id(db: AsyncSession, document_id: UUID, user_id: UUID) -> Document | None:
        """Récupère un document avec ses lignes."""
        statement = (
            select(Document)
            .options(selectinload(Document.items))
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
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
        """Liste les documents avec filtres et pagination."""
        statement = (
            select(Document)
            .options(selectinload(Document.items),selectinload(Document.client) )
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
    async def update_status(
        db: AsyncSession,
        document: Document,
        new_status: DocumentStatus,
    ) -> Document:
        """Change le statut d'un document."""
        valid_transitions = {
            DocumentStatus.DRAFT: [DocumentStatus.SENT],
            DocumentStatus.SENT: [DocumentStatus.VIEWED, DocumentStatus.PAID],
            DocumentStatus.VIEWED: [DocumentStatus.PAID],
            DocumentStatus.PAID: [],
        }

        if new_status not in valid_transitions.get(document.status, []):
            raise ValueError(
                f"Transition invalide : {document.status.value} → {new_status.value}"
            )

        document.status = new_status
        db.add(document)
        await db.flush()  # ← flush() au lieu de commit()
        await db.refresh(document)
        return document

    @staticmethod
    async def update_document(
        db: AsyncSession,
    document: Document,
    client_id: Optional[UUID] = None,
    template_id: Optional[UUID] = None,
    layout_style: Optional[str] = None,
    due_date: Optional[datetime] = None,
    items: Optional[list[dict]] = None,
    notes: Optional[str] = None,
    # ✅ NOUVEAU : Champs de style
    primary_color: Optional[str] = None,
    secondary_color: Optional[str] = None,
    accent_color: Optional[str] = None,
    background_color: Optional[str] = None,
    text_color: Optional[str] = None,
    font_family: Optional[str] = None,
    show_bank_details: Optional[bool] = None,
    show_tax_id: Optional[bool] = None,
    ) -> Document:
        """Met à jour un document."""
        logger.info(f"🔄 update_document appelé pour {document.id}")
        
        if client_id is not None:
            document.client_id = client_id

        if template_id is not None:
            document.template_id = template_id
        if layout_style is not None:
            document.layout_style = layout_style
        if due_date is not None:
            document.due_date = to_naive_utc(due_date)
        if notes is not None:
            document.notes = notes

        if primary_color is not None:
            document.primary_color = primary_color
        if secondary_color is not None:
            document.secondary_color = secondary_color
        if accent_color is not None:
            document.accent_color = accent_color
        if background_color is not None:
            document.background_color = background_color
        if text_color is not None:
            document.text_color = text_color
        if font_family is not None:
            document.font_family = font_family
        if show_bank_details is not None:
            document.show_bank_details = show_bank_details
        if show_tax_id is not None:
            document.show_tax_id = show_tax_id

        if items is not None:
        # Supprimer les anciens items
            for old_item in list(document.items):
                await db.delete(old_item)
            await db.flush()  # ← Flush pour que les suppressions soient effectives
        
        # ✅ Réinitialiser la relation items pour éviter les références fantômes
            document.items = []
        
        # Créer les nouveaux items
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
        logger.info(f"✅ Document {document.id} mis à jour avec {len(document.items)} items")
        return document

    @staticmethod
    async def delete_document(db: AsyncSession, document_id: UUID, user_id: UUID) -> None:
    
    
    # Charger le document avec toutes ses relations
        from sqlalchemy.orm import selectinload
        
        result = await db.execute(
            select(Document)
            .options(
                selectinload(Document.items),
                selectinload(Document.reminder_logs),
                selectinload(Document.views)
            )
            .where(
                Document.id == document_id,
                Document.user_id == user_id
            )
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise ValueError("Document introuvable")
        
        if document.status != DocumentStatus.DRAFT:
            raise ValueError("Seuls les brouillons peuvent être supprimés")
        
        # ✅ La cascade va supprimer automatiquement items, reminder_logs, views
        await db.delete(document)
        await db.commit()
        
        logger.info(f"✅ Document {document.id} supprimé avec cascade")

    @staticmethod
    async def duplicate_as_invoice(db: AsyncSession, document: Document) -> Document:
        """Duplique un devis en facture."""
        if document.type != DocumentType.DEVIS:
            raise ValueError("Seuls les devis peuvent être convertis en facture")

        # Recharger avec les items
        await db.refresh(document, ['items'])

        items_data = [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "tax_rate": item.tax_rate,
            }
            for item in document.items
        ]

        return await DocumentService.create_document(
            db=db,
            type=DocumentType.FACTURE,
            user_id=document.user_id,
            client_id=document.client_id,
            items=items_data,
            layout_style=getattr(document, 'layout_style', 'classic'),
            template_id=document.template_id,
            due_date=document.due_date,
            notes=document.notes,
        )

    @staticmethod
    def calculate_totals(items: list[DocumentItem]) -> dict:
        """Calcule les totaux d'un document."""
        subtotal_cents = 0
        tax_total_cents = 0

        for item in items:
            line_subtotal = item.quantity * item.unit_price_cents
            line_tax = int(line_subtotal * item.tax_rate / 100)
            subtotal_cents += line_subtotal
            tax_total_cents += line_tax

        grand_total_cents = subtotal_cents + tax_total_cents

        return {
            "subtotal_cents": subtotal_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": grand_total_cents,
        }

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
    ) -> str:
        """Génère un aperçu HTML en temps réel."""
        items = items or [{"description": "Exemple", "quantity": 1, "unit_price_cents": 0, "tax_rate": 20}]

        # Template
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

        # Document temporaire
        doc_id = uuid4()
        fake_doc = Document(
            id=doc_id,
            type=type,
            status=DocumentStatus.DRAFT,
            number=reference or "DEV-2026-001",
            created_at=datetime.now(timezone.utc),
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

        # Client temporaire
        fake_client = Client(
            id=uuid4(),
            name=client_name,
            email=client_email,
            address=client_address,
            phone=client_phone,
            user_id=user.id,
        )

        return pdf_renderer.render_html(
            document=fake_doc,
            template=template,
            user=user,
            client=fake_client,
        )

    @staticmethod
    async def _generate_number(db: AsyncSession, type: DocumentType, user_id: UUID) -> str:
        """Génère un numéro automatique."""
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