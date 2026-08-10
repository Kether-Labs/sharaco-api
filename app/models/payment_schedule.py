# app/models/payment_schedule.py
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"       # À facturer
    INVOICED = "INVOICED"     # Facture créée
    PAID = "PAID"             # Payée
    CANCELLED = "CANCELLED"   # Annulée


class PaymentSchedule(SQLModel, table=True):
    """Une échéance / milestone sur un devis."""
    __tablename__ = "payment_schedule"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="document.id", index=True)
    
    # === Config de l'échéance ===
    sequence: int = Field(
        description="Ordre de l'échéance (1, 2, 3...)",
    )
    title: str = Field(
        description="Nom de l'échéance (ex: 'Acompte à la signature')",
        max_length=255,
    )
    percent: float = Field(
        description="Pourcentage du devis (ex: 30.0 pour 30%)",
        ge=0, le=100,
    )
    amount_cents: int = Field(
        description="Montant calculé en centimes",
    )
    description: Optional[str] = Field(
        default=None,
        description="Description optionnelle (conditions, livrables...)",
    )
    
    # === Déclenchement ===
    trigger_date: Optional[datetime] = Field(
        default=None,
        description="Date prévue de facturation (optionnel)",
    )
    
    # === Statut ===
    status: MilestoneStatus = Field(default=MilestoneStatus.PENDING)
    
    # === Lien vers la facture générée ===
    invoice_id: Optional[UUID] = Field(
        default=None,
        foreign_key="document.id",
        index=True,
        description="Facture générée pour cette échéance",
    )
    
    invoiced_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    
    # === Relations ===
    document: "Document" = Relationship(
        back_populates="payment_schedule",
        sa_relationship_kwargs={"foreign_keys": "PaymentSchedule.document_id"},
    )
    invoice: Optional["Document"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "PaymentSchedule.invoice_id",
            "remote_side": "Document.id",
        }
    )