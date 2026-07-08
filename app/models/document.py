from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from app.utils.datetime import to_naive_utc
import secrets

def _utcnow_naive() -> datetime:
    """Retourne l'heure UTC naive (sans timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class DocumentType(str, Enum):
    DEVIS = "DEVIS"
    FACTURE = "FACTURE"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"  
    REFUSED = "REFUSED" 
    PAID = "PAID"
    VIEWED = "VIEWED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: DocumentType = Field(default=DocumentType.DEVIS)
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT)
    number: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=_utcnow_naive)
    due_date: Optional[datetime] = None
    sent_at: Optional[datetime] = None  # Date d'envoi par email
    viewed_at: Optional[datetime] = None  # Première visualisation
    notes: Optional[str] = Field(default=None, description="Notes/conditions visibles sur le document")

    accepted_at: Optional[datetime] = None
    refused_at: Optional[datetime] = None
    refusal_reason: Optional[str] = None
    signature_name: Optional[str] = Field(default=None, max_length=255)

    share_token: Optional[str] = Field(
        default=None,
        index=True,
        unique=True,
        max_length=64,
        description="Token unique pour le partage public du document"
    )
    share_enabled: bool = Field(
        default=False,
        description="Activer/désactiver le partage public"
    )
    share_expires_at: Optional[datetime] = Field(
        default=None,
        description="Date d'expiration du lien de partage"
    )

    @staticmethod
    def generate_share_token() -> str:
        """Génère un token sécurisé de 32 caractères."""
        return secrets.token_urlsafe(32)
    
    # === Relations ===
    owner: "User" = Relationship(back_populates="documents")
    user_id: UUID = Field(foreign_key="user.id")
    client_id: UUID = Field(foreign_key="client.id")
    client: "Client" = Relationship(back_populates="documents")


    layout_style: str = Field(
        default="classic",
        description="Style de layout prédéfini (modern, classic, minimal, bold, elegant)"
    )
    # === Template de design ===
    template_id: Optional[UUID] = Field(
        default=None,
        foreign_key="documenttemplate.id",
        description="Template personnalisé (UUID). Si null, utilise layout_style."
    )
    template: Optional["DocumentTemplate"] = Relationship(back_populates="documents")

    project_id: Optional[UUID] = Field(
        default=None,
        foreign_key="project.id",
        description="Projet associé (null si document hors projet)"
    )
    project: Optional["Project"] = Relationship(back_populates="documents")
    
    primary_color: Optional[str] = Field(default="#2563EB")
    secondary_color: Optional[str] = Field(default="#1E40AF")
    accent_color: Optional[str] = Field(default="#DBEAFE")
    background_color: Optional[str] = Field(default="#FFFFFF")
    text_color: Optional[str] = Field(default="#1F2937")
    font_family: Optional[str] = Field(default="Inter")
    show_bank_details: bool = Field(default=True)
    show_tax_id: bool = Field(default=True)

    # === Lignes du document ===
    items: List["DocumentItem"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    # === Relances & Tracking ===
    reminder_logs: List["ReminderLog"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    views: List["DocumentView"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DocumentItem(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    description: str
    quantity: int = 1
    unit_price_cents: int
    tax_rate: int = 20

    document_id: UUID = Field(foreign_key="document.id")
    document: Document = Relationship(back_populates="items")