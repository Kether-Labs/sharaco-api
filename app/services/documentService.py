from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, DocumentItem, DocumentType, DocumentStatus
from app.models.document_template import DocumentTemplate
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone


class DocumentService:
    @staticmethod
    async def create_document(
        db: AsyncSession,
        type: DocumentType,
        user_id: UUID,
        client_id: UUID,
        items: list[dict],
        template_id: Optional[UUID] = None,
        due_date: Optional[datetime] = None,
    ) -> Document:
        """Crée un document (devis/facture) avec ses lignes et sa numérotation auto."""

        # Vérifier le template si fourni
        if template_id:
            tmpl = await db.execute(
                select(DocumentTemplate).where(
                    DocumentTemplate.id == template_id,
                    DocumentTemplate.user_id == user_id,
                )
            )
            if not tmpl.scalar_one_or_none():
                raise ValueError("Template introuvable ou n'appartient pas à cet utilisateur")

        # Générer le numéro automatique
        number = await DocumentService._generate_number(db, type, user_id)

        # Créer le document
        document = Document(
            type=type,
            status=DocumentStatus.DRAFT,
            number=number,
            user_id=user_id,
            client_id=client_id,
            template_id=template_id,
            due_date=due_date,
        )
        db.add(document)
        await db.flush()  # Pour obtenir l'ID du document

        # Créer les lignes
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
        await db.refresh(document)
        return document

    @staticmethod
    async def get_by_id(db: AsyncSession, document_id: UUID, user_id: UUID) -> Document | None:
        """Récupère un document avec ses lignes, en vérifiant l'appartenance."""
        statement = select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
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
        skip: int = 0,
        limit: int = 50,
    ) -> list[Document]:
        """Liste les documents avec filtres et pagination."""
        statement = select(Document).where(Document.user_id == user_id)

        if type:
            statement = statement.where(Document.type == type)
        if status:
            statement = statement.where(Document.status == status)
        if client_id:
            statement = statement.where(Document.client_id == client_id)

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
        # Règles de transition
        valid_transitions = {
            DocumentStatus.DRAFT: [DocumentStatus.SENT],
            DocumentStatus.SENT: [DocumentStatus.PAID],
            DocumentStatus.PAID: [],  # Pas de retour possible
        }

        if new_status not in valid_transitions.get(document.status, []):
            raise ValueError(
                f"Transition invalide : {document.status.value} → {new_status.value}"
            )

        document.status = new_status
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    @staticmethod
    async def update_document(
        db: AsyncSession,
        document: Document,
        due_date: Optional[datetime] = None,
        template_id: Optional[UUID] = None,
    ) -> Document:
        """Met à jour les champs modifiables d'un document."""
        if due_date is not None:
            document.due_date = due_date
        if template_id is not None:
            document.template_id = template_id

        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    @staticmethod
    async def delete_document(db: AsyncSession, document: Document) -> None:
        """Supprime un document (seulement si DRAFT)."""
        if document.status != DocumentStatus.DRAFT:
            raise ValueError("Seuls les brouillons peuvent être supprimés")
        await db.delete(document)
        await db.commit()

    @staticmethod
    async def duplicate_as_invoice(db: AsyncSession, document: Document) -> Document:
        """Duplique un devis en facture."""
        if document.type != DocumentType.DEVIS:
            raise ValueError("Seuls les devis peuvent être convertis en facture")

        # Recharger avec les items
        stmt = select(Document).where(Document.id == document.id)
        result = await db.execute(stmt)
        doc_with_items = result.scalar_one()

        items_data = [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "tax_rate": item.tax_rate,
            }
            for item in doc_with_items.items
        ]

        return await DocumentService.create_document(
            db=db,
            type=DocumentType.FACTURE,
            user_id=document.user_id,
            client_id=document.client_id,
            items=items_data,
            template_id=document.template_id,
            due_date=document.due_date,
        )

    @staticmethod
    def calculate_totals(items: list[DocumentItem]) -> dict:
        """Calcule les totaux d'un document à partir de ses lignes."""
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
    async def _generate_number(db: AsyncSession, type: DocumentType, user_id: UUID) -> str:
        """Génère un numéro de document automatique (DEV-2026-001, FACT-2026-001)."""
        prefix = "DEV" if type == DocumentType.DEVIS else "FACT"
        year = datetime.now(timezone.utc).year

        # Compter les documents de cette année pour cet utilisateur
        count_stmt = (
            select(func.count(Document.id))
            .where(
                Document.user_id == user_id,
                Document.type == type,
            )
        )
        result = await db.execute(count_stmt)
        count = result.scalar() or 0

        return f"{prefix}-{year}-{count + 1:03d}"
