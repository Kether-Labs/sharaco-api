# app/schemas/document.py

from pydantic import BaseModel, field_validator,Field
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

class DocumentProjectLink(BaseModel):
    """Associer un document à un projet."""
    project_id: Optional[UUID] = Field(None, description="ID du projet (null pour retirer l'association)")

class DocumentItemRead(BaseModel):
    id: UUID
    description: str
    quantity: int
    unit_price_cents: int
    tax_rate: int

    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    """Création d'un document."""
    id: Optional[UUID] = None
    type: DocumentType = DocumentType.DEVIS
    client_id: Optional[UUID] = None
    layout_style: str = "classic"
    template_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    items: List[DocumentItemCreate]
    notes: Optional[str] = None
    project_id: Optional[UUID] = Field(None, description="ID du projet associé (optionnel)")
    # ✅ Champs de style
    primary_color: Optional[str] = "#2563EB"
    secondary_color: Optional[str] = "#1E40AF"
    accent_color: Optional[str] = "#DBEAFE"
    background_color: Optional[str] = "#FFFFFF"
    text_color: Optional[str] = "#1F2937"
    font_family: Optional[str] = "Inter"
    show_bank_details: Optional[bool] = True
    show_tax_id: Optional[bool] = True

    @field_validator("layout_style")
    @classmethod
    def validate_layout_style(cls, v: Optional[str]) -> Optional[str]:
        valid_layouts = ["modern", "classic", "minimal", "bold", "elegant"]
        if v and v not in valid_layouts:
            raise ValueError(f"Layout invalide. Options: {', '.join(valid_layouts)}")
        return v or "classic"

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
    sent_at: Optional[datetime] = None
    viewed_at: Optional[datetime] = None
    user_id: UUID
    client_id: UUID
    template_id: Optional[UUID] = None
    layout_style: str = "classic"
    items: List[DocumentItemRead] = []
    notes: Optional[str] = None
    project_id: Optional[UUID] = None
    
    # ✅ Champs de style
    primary_color: Optional[str] = "#2563EB"
    secondary_color: Optional[str] = "#1E40AF"
    accent_color: Optional[str] = "#DBEAFE"
    background_color: Optional[str] = "#FFFFFF"
    text_color: Optional[str] = "#1F2937"
    font_family: Optional[str] = "Inter"
    show_bank_details: bool = True
    show_tax_id: bool = True

    # Totaux calculés
    subtotal_cents: Optional[int] = None
    tax_total_cents: Optional[int] = None
    grand_total_cents: Optional[int] = None

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    """Mise à jour complète d'un document."""
    client_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    layout_style: Optional[str] = None
    due_date: Optional[datetime] = None
    items: Optional[List[DocumentItemCreate]] = None
    notes: Optional[str] = None
    
    # ✅ NOUVEAU : Champs de style/couleurs
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    font_family: Optional[str] = None
    show_bank_details: Optional[bool] = None
    show_tax_id: Optional[bool] = None

    @field_validator("layout_style")
    @classmethod
    def validate_layout_style(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        valid_layouts = ["modern", "classic", "minimal", "bold", "elegant"]
        if v not in valid_layouts:
            raise ValueError(f"Layout invalide. Options: {', '.join(valid_layouts)}")
        return v


class DocumentStatusUpdate(BaseModel):
    status: DocumentStatus


class DocumentPreviewItem(BaseModel):
    description: str = ""
    quantity: int = 1
    unit_price_cents: int = 0
    tax_rate: int = 20


class DocumentPreviewRequest(BaseModel):
    type: Optional[str] = "DEVIS"
    client_name: str = "Client Exemple"
    client_email: str = ""
    client_address: str = ""
    client_phone: str = ""
    items: List[DocumentPreviewItem] = []
    template_id: Optional[str] = None
    layout_style: str = "classic"
    primary_color: str = "#2563EB"
    secondary_color: str = "#1E40AF"
    accent_color: str = "#DBEAFE"
    text_color: str = "#1F2937"
    background_color: str = "#FFFFFF"
    font_family: str = "Inter"
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    show_bank_details: bool = True
    show_tax_id: bool = True
    notes: Optional[str] = None
    reference: Optional[str] = None


class DocumentListRead(BaseModel):
    id: UUID
    type: DocumentType
    status: DocumentStatus
    number: Optional[str] = None
    created_at: datetime
    due_date: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    viewed_at: Optional[datetime] = None
    client_id: UUID
    template_id: Optional[UUID] = None
    layout_style: str = "classic"
    grand_total_cents: Optional[int] = None
    project_id: Optional[UUID] = None
    model_config = {"from_attributes": True}