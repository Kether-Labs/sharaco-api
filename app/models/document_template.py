from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentTemplate(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(nullable=False, description="Nom du template (ex: Classique, Moderne)")

    # === Propriétaire ===
    user_id: UUID = Field(foreign_key="user.id")
    owner: "User" = Relationship(back_populates="templates")

    # === Couleurs ===
    primary_color: str = Field(default="#2563EB", description="Couleur principale (hex)")
    secondary_color: str = Field(default="#1E40AF", description="Couleur secondaire (hex)")
    accent_color: str = Field(default="#DBEAFE", description="Couleur d'accent (hex)")
    text_color: str = Field(default="#1F2937", description="Couleur du texte (hex)")
    background_color: str = Field(default="#FFFFFF", description="Couleur de fond (hex)")

    # === Logo ===
    logo_url: Optional[str] = Field(default=None, description="URL du logo entreprise")

    # === Typographie ===
    font_family: str = Field(default="Inter", description="Police principale")

    # === Contenu personnalisable ===
    header_text: Optional[str] = Field(default=None, description="Texte en-tête personnalisé")
    footer_text: Optional[str] = Field(default=None, description="Texte pied de page (mentions légales, etc.)")
    show_bank_details: bool = Field(default=True, description="Afficher les coordonnées bancaires")
    show_tax_id: bool = Field(default=True, description="Afficher le NIF/SIRET")

    # === Layout ===
    layout_style: str = Field(
        default="classic",
        description="Style de mise en page : classic, modern, minimal"
    )

    # === Meta ===
    is_default: bool = Field(default=False, description="Template par défaut de l'utilisateur")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # === Relations ===
    documents: List["Document"] = Relationship(back_populates="template")
