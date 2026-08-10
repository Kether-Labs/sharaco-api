# app/models/billing_settings.py
from sqlmodel import SQLModel, Field
from uuid import UUID
from datetime import datetime


class BillingSettings(SQLModel, table=True):
    __tablename__ = "billing_settings"

    id: UUID = Field(default_factory=__import__('uuid').uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", unique=True, index=True)

    # === Automatisation ===
    auto_create_invoice: bool = Field(
        default=True,
        description="Crée automatiquement une facture brouillon quand un devis est accepté",
    )
    auto_send_invoice: bool = Field(
        default=False,
        description="Envoie automatiquement la facture au client (dangereux — opt-in)",
    )
    acompte_percent: float | None = Field(
        default=None,
        description="Pourcentage d'acompte à facturer à l'acceptation (ex: 30.0). None = pas d'acompte",
    )

    # === Numérotation ===
    invoice_prefix: str = Field(default="FACT", max_length=10)
    invoice_number_format: str = Field(
        default="{prefix}-{year}-{seq:03d}",
        description="Format du numéro (placeholders: prefix, year, seq)",
    )

    # === Conditions de paiement ===
    default_payment_terms_days: int = Field(
        default=30,
        description="Délai de paiement par défaut (jours)",
    )
    default_late_fee_percent: float = Field(
        default=1.5,
        description="Pénalités de retard par mois (%)",
    )

    # === Mentions légales ===
    legal_mentions: str | None = Field(
        default=None,
        description="Mentions légales ajoutées en bas de facture",
    )

    # === Métadonnées ===
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        sa_column_kwargs={"onupdate": lambda: datetime.utcnow()}
    )