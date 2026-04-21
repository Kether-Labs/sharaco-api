from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum


class DocumentType(str, Enum):
    DEVIS = "DEVIS"
    FACTURE = "FACTURE"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PAID = "PAID"
    VIEWED = "VIEWED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: DocumentType = Field(default=DocumentType.DEVIS)
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT)
    number: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=_utcnow)
    due_date: Optional[datetime] = None
    sent_at: Optional[datetime] = None  # Date d'envoi par email
    viewed_at: Optional[datetime] = None  # Première visualisation

    # === Relations ===
    owner: "User" = Relationship(back_populates="documents")
    user_id: UUID = Field(foreign_key="user.id")
    client_id: UUID = Field(foreign_key="client.id")
    client: "Client" = Relationship(back_populates="documents")

    # === Template de design ===
    template_id: Optional[UUID] = Field(
        default=None,
        foreign_key="documenttemplate.id",
        description="Template de design appliqué au document"
    )
    template: Optional["DocumentTemplate"] = Relationship(back_populates="documents")

    # === Lignes du document ===
    items: List["DocumentItem"] = Relationship(back_populates="document")

    # === Relances & Tracking ===
    reminder_logs: List["ReminderLog"] = Relationship(back_populates="document")
    views: List["DocumentView"] = Relationship(back_populates="document")


class DocumentItem(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    description: str
    quantity: int = 1
    unit_price_cents: int
    tax_rate: int = 20

    document_id: UUID = Field(foreign_key="document.id")
    document: Document = Relationship(back_populates="items")
