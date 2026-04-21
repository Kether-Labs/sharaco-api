from pydantic import BaseModel, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime


class DocumentTemplateCreate(BaseModel):
    name: str
    primary_color: str = "#2563EB"
    secondary_color: str = "#1E40AF"
    accent_color: str = "#DBEAFE"
    text_color: str = "#1F2937"
    background_color: str = "#FFFFFF"
    logo_url: Optional[str] = None
    font_family: str = "Inter"
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    show_bank_details: bool = True
    show_tax_id: bool = True
    layout_style: str = "classic"
    is_default: bool = False

    @field_validator("primary_color", "secondary_color", "accent_color", "text_color", "background_color")
    @classmethod
    def color_must_be_hex(cls, v: str) -> str:
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError(f"Couleur hex invalide : {v}. Format attendu : #RRGGBB ou #RGB")
        return v

    @field_validator("layout_style")
    @classmethod
    def layout_style_valid(cls, v: str) -> str:
        allowed = {"classic", "modern", "minimal"}
        if v not in allowed:
            raise ValueError(f"Layout '{v}' invalide. Choix possibles : {', '.join(allowed)}")
        return v


class DocumentTemplateRead(BaseModel):
    id: UUID
    name: str
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    background_color: str
    logo_url: Optional[str] = None
    font_family: str
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    show_bank_details: bool
    show_tax_id: bool
    layout_style: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentTemplateUpdate(BaseModel):
    name: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    text_color: Optional[str] = None
    background_color: Optional[str] = None
    logo_url: Optional[str] = None
    font_family: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    show_bank_details: Optional[bool] = None
    show_tax_id: Optional[bool] = None
    layout_style: Optional[str] = None
    is_default: Optional[bool] = None
