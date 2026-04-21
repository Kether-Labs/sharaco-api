from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ReminderConfig(SQLModel, table=True):
    """Configuration des relances automatiques par utilisateur."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    owner: "User" = Relationship(back_populates="reminder_configs")

    # Relance J+1 : rappel doux
    reminder_1_enabled: bool = Field(default=True, description="Activer la relance J+1")
    reminder_1_days: int = Field(default=1, description="Nombre de jours après envoi")
    reminder_1_subject: str = Field(
        default="Rappel : Votre devis {number} est en attente",
        description="Sujet de l'email (supporte {number}, {company})"
    )

    # Relance J+3 : relance medium
    reminder_2_enabled: bool = Field(default=True, description="Activer la relance J+3")
    reminder_2_days: int = Field(default=3, description="Nombre de jours après envoi")
    reminder_2_subject: str = Field(
        default="Suivi : Devis {number} - Avez-vous bien reçu ?",
        description="Sujet de l'email"
    )

    # Relance J+7 : relance forte
    reminder_3_enabled: bool = Field(default=False, description="Activer la relance J+7")
    reminder_3_days: int = Field(default=7, description="Nombre de jours après envoi")
    reminder_3_subject: str = Field(
        default="Dernier rappel : Devis {number} expire bientôt",
        description="Sujet de l'email"
    )

    # Paramètres généraux
    is_active: bool = Field(default=True, description="Activer les relances auto")
    stop_on_view: bool = Field(default=True, description="Arrêter les relances si le devis est vu")
    stop_on_payment: bool = Field(default=True, description="Arrêter les relances si le devis est payé")

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ReminderLog(SQLModel, table=True):
    """Historique des relances envoyées."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="document.id", index=True)
    document: "Document" = Relationship(back_populates="reminder_logs")

    reminder_level: int = Field(description="Niveau de relance (1, 2 ou 3)")
    status: ReminderStatus = Field(default=ReminderStatus.PENDING)
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None


class DocumentView(SQLModel, table=True):
    """Tracking des ouvertures de documents."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="document.id", index=True)
    document: "Document" = Relationship(back_populates="views")

    viewed_at: datetime = Field(default_factory=_utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None