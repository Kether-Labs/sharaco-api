# app/models/invoice_reminder.py
from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum


class InvoiceReminderType(str, Enum):
    DUE_3_DAYS = "DUE_3_DAYS"   # échéance dans 3 jours
    DUE_1_DAY = "DUE_1_DAY"     # échéance demain


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InvoiceReminder(SQLModel, table=True):
    """Journal des rappels envoyés (évite les doublons)."""
    __tablename__ = "invoice_reminders"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    invoice_id: UUID = Field(foreign_key="document.id", index=True)
    reminder_type: str = Field(index=True)
    recipient_email: str
    sent_at: datetime = Field(default_factory=_utcnow_naive)