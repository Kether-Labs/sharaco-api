from pydantic import BaseModel, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.models.document import DocumentType, DocumentStatus


class DocumentItemCreate(BaseModel):
    description: str
    quantity: int = 1
    unit_price_cents: int
    tax_rate: int = 20

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("La quantité doit être positive")
        return v

    @field_validator("unit_price_cents")
    @classmethod
    def price_must_be_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Le prix unitaire ne peut pas être négatif")
        return v

    @field_validator("tax_rate")
    @classmethod
    def tax_rate_valid(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError("Le taux de TVA doit être entre 0 et 100")
        return v


class DocumentItemRead(BaseModel):
    id: UUID
    description: str
    quantity: int
    unit_price_cents: int
    tax_rate: int

    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    type: DocumentType = DocumentType.DEVIS
    client_id: UUID
    due_date: Optional[datetime] = None
    items: List[DocumentItemCreate]

    @field_validator("items")
    @classmethod
    def items_must_not_be_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("Un document doit contenir au moins une ligne")
        return v


class DocumentRead(BaseModel):
    id: UUID
    type: DocumentType
    status: DocumentStatus
    number: Optional[str] = None
    created_at: datetime
    due_date: Optional[datetime] = None
    user_id: UUID
    client_id: UUID
    items: List[DocumentItemRead] = []

    # Totaux calculés (pas en DB, calculés à la volée)
    subtotal_cents: Optional[int] = None
    tax_total_cents: Optional[int] = None
    grand_total_cents: Optional[int] = None

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    status: Optional[DocumentStatus] = None
    due_date: Optional[datetime] = None


class DocumentStatusUpdate(BaseModel):
    status: DocumentStatus


class DocumentListRead(BaseModel):
    """Version allégée pour les listes (sans items détaillés)."""
    id: UUID
    type: DocumentType
    status: DocumentStatus
    number: Optional[str] = None
    created_at: datetime
    due_date: Optional[datetime] = None
    client_id: UUID
    grand_total_cents: Optional[int] = None

    model_config = {"from_attributes": True}