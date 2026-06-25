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
    """Création d'un document — l'ID peut être fourni par le frontend."""
    id: Optional[UUID] = None  # UUID fourni par le frontend, auto-généré si absent
    type: DocumentType = DocumentType.DEVIS
    client_id: Optional[UUID] = None
    
    layout_style: str = "classic"  # Style prédéfini (modern, classic, etc.)
    template_id: Optional[UUID] = None  # Template personnalisé (UUID ou None)
    due_date: Optional[datetime] = None
    items: List[DocumentItemCreate]
    notes: Optional[str] = None


    @field_validator("layout_style")
    @classmethod
    def validate_layout_style(cls, v: str) -> str:
        valid_layouts = ["modern", "classic", "minimal", "bold", "elegant"]
        if v not in valid_layouts:
            raise ValueError(f"Layout invalide. Options: {', '.join(valid_layouts)}")
        return v
    
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
    template_id: Optional[str] = None
    items: List[DocumentItemRead] = []
    notes: Optional[str] = None

    # Totaux calculés
    subtotal_cents: Optional[int] = None
    tax_total_cents: Optional[int] = None
    grand_total_cents: Optional[int] = None

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    """Mise à jour complète d'un document (items, client, template...)."""
    client_id: Optional[UUID] = None
    template_id: Optional[str] = None
    layout_style: Optional[str] = None 
    due_date: Optional[datetime] = None
    items: Optional[List[DocumentItemCreate]] = None
    notes: Optional[str] = None

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
    """Ligne d'article pour l'aperçu en temps réel."""
    description: str = ""
    quantity: int = 1
    unit_price_cents: int = 0
    tax_rate: int = 20


class DocumentPreviewRequest(BaseModel):
    """Données pour l'aperçu en temps réel (pas de sauvegarde en DB).
    Validation permissive : l'utilisateur est en train d'éditer,
    les champs peuvent être vides ou incomplets.
    """
    type: Optional[str] = "DEVIS"
    # Client
    client_name: str = "Client Exemple"
    client_email: str = ""
    client_address: str = ""
    client_phone: str = ""
    # Articles
    items: List[DocumentPreviewItem] = []
    # Template
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
    # Méta
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
    template_id: Optional[str] = None
    grand_total_cents: Optional[int] = None

    model_config = {"from_attributes": True}
